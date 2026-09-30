/// forge_brain_worker — Rust port of brain_worker.py
/// ZMQ REP :5557 | msgpack | BGE-M3 ONNX + DirectML
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};
use std::thread;

// Mutex global serialisation acces iGPU DirectML (anti-saturation TDR).
// Mutex::new() est const depuis Rust 1.63 -> pas besoin lazy_static.
// Le lock englobe le call ORT + sleep => aucun autre thread/process ne peut
// soumettre du travail au GPU pendant la fenetre breathing room DWM compositor.
static DIRECTML_MUTEX: Mutex<()> = Mutex::new(());

use half::f16;
use ort::session::Session;
use ort::execution_providers::{DirectMLExecutionProvider, CPUExecutionProvider};
use ort::value::Tensor;
use rmp_serde::{from_slice, to_vec_named};
use serde::{Deserialize, Serialize};
use tokenizers::Tokenizer;
use log::{info, warn, error, debug};

const ZMQ_ADDR: &str = "tcp://127.0.0.1:5557";
const MAX_LENGTH: usize = 512;
const EMBED_DIM: usize = 1024;

// ── Wire types ────────────────────────────────────────────────────────────────

#[derive(Deserialize, Debug)]
struct Request {
    cmd: String,
    texts: Option<Vec<String>>,
    task_id: Option<String>,
    priority: Option<i64>,
}

#[derive(Serialize)]
struct SubmitReply { ok: bool, task_id: String, priority: i64 }

#[derive(Serialize)]
struct CheckReply {
    ok: bool,
    status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    data: Option<EmbedData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
}

#[derive(Serialize, Clone)]
struct EmbedData { vecs: Vec<Vec<f32>> }

// ── Task state ────────────────────────────────────────────────────────────────

#[derive(Clone)]
enum TaskState {
    Pending(Vec<String>),
    Completed(EmbedData),
    Error(String),
}

type TaskMap = Arc<Mutex<HashMap<String, TaskState>>>;

// ── Embedder ──────────────────────────────────────────────────────────────────

struct Embedder {
    session: Session,
    tokenizer: Tokenizer,
}

impl Embedder {
    fn new(model_path: &std::path::Path, tok_path: &std::path::Path) -> anyhow::Result<Self> {
        // LAFORGE_EMBED_DEVICE = cpu (defaut) | directml
        // DirectML sur Radeon 780M iGPU declenche TDR + BSOD 0x119 sous batch BGE-M3 continu.
        // Defaut CPU jusqu a routage NPU/dGPU dedie.
        let device = std::env::var("LAFORGE_EMBED_DEVICE")
            .unwrap_or_else(|_| "cpu".to_string())
            .to_lowercase();
        info!("[brain-worker] execution provider: {device}");

        let builder = Session::builder()
            .map_err(|e| anyhow::anyhow!("session builder: {e:?}"))?;
        let session = if device == "directml" {
            builder.with_execution_providers([
                DirectMLExecutionProvider::default().build(),
                CPUExecutionProvider::default().build(),
            ])
        } else {
            builder.with_execution_providers([
                CPUExecutionProvider::default().build(),
            ])
        }
            .map_err(|e| anyhow::anyhow!("exec providers: {e:?}"))?
            .commit_from_file(model_path)
            .map_err(|e| anyhow::anyhow!("load model: {e:?}"))?;

        let tokenizer = Tokenizer::from_file(tok_path)
            .map_err(|e| anyhow::anyhow!("tokenizer: {e}"))?;

        info!("[brain-worker] model loaded: {}", model_path.display());
        Ok(Self { session, tokenizer })
    }

    fn embed(&mut self, texts: &[String]) -> anyhow::Result<Vec<Vec<f32>>> {
        if texts.is_empty() { return Ok(vec![]); }

        // Phase 3 safety : si DirectML, hard-cap batch via LAFORGE_EMBED_BATCH_CAP (default=4).
        // Evite saturation video_scheduler -> TDR -> BSOD 0x119 (incident 2026-05-24).
        // Si batch entrant > cap, split en mini-batches sequentiels avec sleep entre chaque.
        let device = std::env::var("LAFORGE_EMBED_DEVICE")
            .unwrap_or_else(|_| "cpu".to_string())
            .to_lowercase();
        let batch_cap: usize = std::env::var("LAFORGE_EMBED_BATCH_CAP")
            .ok().and_then(|s| s.parse().ok())
            .unwrap_or(if device == "directml" { 4 } else { 32 });

        if texts.len() > batch_cap {
            let mut all_vecs: Vec<Vec<f32>> = Vec::with_capacity(texts.len());
            for chunk in texts.chunks(batch_cap) {
                // Lock GPU global pour DirectML : evite cascade saturation
                // si plusieurs threads/processes tentent embed concurrent.
                if device == "directml" {
                    let _gpu_lock = DIRECTML_MUTEX.lock().unwrap();
                    let chunk_vecs = self.embed_inner(chunk)?;
                    all_vecs.extend(chunk_vecs);
                    // sleep ENGLOBE par le lock => DWM breathing room garantie
                    std::thread::sleep(std::time::Duration::from_millis(50));
                    // _gpu_lock libere ici (fin de scope), apres le sleep
                } else {
                    let chunk_vecs = self.embed_inner(chunk)?;
                    all_vecs.extend(chunk_vecs);
                }
            }
            return Ok(all_vecs);
        }
        // Single batch <= cap : lock GPU si DirectML
        if device == "directml" {
            let _gpu_lock = DIRECTML_MUTEX.lock().unwrap();
            self.embed_inner(texts)
        } else {
            self.embed_inner(texts)
        }
    }

    fn embed_inner(&mut self, texts: &[String]) -> anyhow::Result<Vec<Vec<f32>>> {
        let batch = texts.len();

        let encodings = self.tokenizer
            .encode_batch(texts.to_vec(), true)
            .map_err(|e| anyhow::anyhow!("tokenize: {e}"))?;

        let seq_len = encodings.iter()
            .map(|e| e.get_ids().len()).max().unwrap_or(0).min(MAX_LENGTH);

        let mut ids_flat  = vec![0i64; batch * seq_len];
        let mut mask_flat = vec![0i64; batch * seq_len];

        for (i, enc) in encodings.iter().enumerate() {
            let ids  = enc.get_ids();
            let mask = enc.get_attention_mask();
            let len  = ids.len().min(seq_len);
            for j in 0..len {
                ids_flat [i * seq_len + j] = ids[j]  as i64;
                mask_flat[i * seq_len + j] = mask[j] as i64;
            }
        }

        // (shape, vec) form — avoids ndarray version conflict with ort
        let ids_t  = Tensor::<i64>::from_array(([batch, seq_len], ids_flat))
            .map_err(|e| anyhow::anyhow!("ids tensor: {e:?}"))?;
        let mask_t = Tensor::<i64>::from_array(([batch, seq_len], mask_flat))
            .map_err(|e| anyhow::anyhow!("mask tensor: {e:?}"))?;

        let outputs = self.session.run(ort::inputs![
            "input_ids"      => ids_t,
            "attention_mask" => mask_t,
        ])?;

        // Model outputs f16 — ort RC12 has no f16 PrimitiveTensorElementType
        // Extract raw u16 bits, reinterpret via half::f16::from_bits()
        // Shape: [batch, seq_len, 1024] row-major
        // CLS token [i, 0, k] = slice[i * seq_len * EMBED_DIM + k]
        let (_, hidden_f16) = outputs["last_hidden_state"]
            .try_extract_tensor::<f16>()
            .map_err(|e| anyhow::anyhow!("extract tensor: {e:?}"))?;

        let mut vecs = Vec::with_capacity(batch);
        for i in 0..batch {
            let offset = i * seq_len * EMBED_DIM;
            let cls: Vec<f32> = hidden_f16[offset..offset + EMBED_DIM]
                .iter().map(|x| x.to_f32()).collect();
            let norm: f32 = cls.iter().map(|x| x * x).sum::<f32>().sqrt().max(1e-9);
            vecs.push(cls.iter().map(|x| x / norm).collect());
        }
        Ok(vecs)
    }
}

// ── Worker thread ─────────────────────────────────────────────────────────────

fn worker_loop(embedder: Arc<Mutex<Embedder>>, tasks: TaskMap) {
    loop {
        let pending = {
            let map = tasks.lock().unwrap();
            map.iter().find_map(|(id, st)| {
                if let TaskState::Pending(texts) = st {
                    Some((id.clone(), texts.clone()))
                } else { None }
            })
        };
        if let Some((tid, texts)) = pending {
            debug!("[brain-worker] task {tid} {} texts", texts.len());
            match embedder.lock().unwrap().embed(&texts) {
                Ok(vecs) => {
                    tasks.lock().unwrap().insert(tid.clone(), TaskState::Completed(EmbedData { vecs }));
                    debug!("[brain-worker] task {tid} done");
                }
                Err(e) => {
                    error!("[brain-worker] task {tid} err: {e}");
                    tasks.lock().unwrap().insert(tid, TaskState::Error(e.to_string()));
                }
            }
        } else {
            thread::sleep(std::time::Duration::from_millis(5));
        }
    }
}

// ── Main ──────────────────────────────────────────────────────────────────────

fn main() -> anyhow::Result<()> {
    env_logger::Builder::from_env(
        env_logger::Env::default().default_filter_or("info")
    ).init();

    // exe: LaForge/go_services/forge_brain_worker/target/release/forge_brain_worker.exe
    // nth(5) = LaForge/
    let root = std::env::var("LAFORGE_ROOT").map(PathBuf::from)
        .unwrap_or_else(|_| {
            std::env::current_exe().unwrap()
                .ancestors().nth(5).unwrap().to_path_buf()
        });

    let model_path = root.join("models/bge_m3_onnx/model.onnx");
    let tok_path   = root.join("models/bge_m3_onnx/tokenizer.json");
    info!("[brain-worker] root={}", root.display());

    let embedder = Arc::new(Mutex::new(Embedder::new(&model_path, &tok_path)?));
    let tasks: TaskMap = Arc::new(Mutex::new(HashMap::new()));

    { // worker thread
        let emb = Arc::clone(&embedder);
        let tsk = Arc::clone(&tasks);
        thread::spawn(move || worker_loop(emb, tsk));
    }

    let ctx = zmq::Context::new();
    let socket = ctx.socket(zmq::REP)?;
    socket.bind(ZMQ_ADDR)?;
    info!("[brain-worker] ZMQ REP on {ZMQ_ADDR}");

    loop {
        let bytes = socket.recv_bytes(0)?;
        let req: Request = match from_slice(&bytes) {
            Ok(r) => r,
            Err(e) => {
                warn!("[brain-worker] bad msgpack: {e}");
                socket.send(to_vec_named(&serde_json::json!({"ok":false,"error":e.to_string()}))?, 0)?;
                continue;
            }
        };

        match req.cmd.as_str() {
            "submit" => {
                let texts    = req.texts.unwrap_or_default();
                let priority = req.priority.unwrap_or(10);
                let task_id  = format!("t_{}", SystemTime::now()
                    .duration_since(UNIX_EPOCH).unwrap().as_millis());
                tasks.lock().unwrap().insert(task_id.clone(), TaskState::Pending(texts));
                socket.send(to_vec_named(&SubmitReply { ok: true, task_id, priority })?, 0)?;
            }
            "check" => {
                let tid   = req.task_id.unwrap_or_default();
                let state = tasks.lock().unwrap().get(&tid).cloned();
                let reply = match state {
                    None                          => to_vec_named(&CheckReply { ok: false, status: "unknown".into(),   data: None, error: Some("not found".into()) })?,
                    Some(TaskState::Pending(_))   => to_vec_named(&CheckReply { ok: true,  status: "pending".into(),   data: None, error: None })?,
                    Some(TaskState::Completed(d)) => to_vec_named(&CheckReply { ok: true,  status: "completed".into(), data: Some(d), error: None })?,
                    Some(TaskState::Error(e))     => to_vec_named(&CheckReply { ok: false, status: "error".into(),     data: None, error: Some(e) })?,
                };
                socket.send(reply, 0)?;
            }
            other => {
                warn!("[brain-worker] unknown cmd: {other}");
                socket.send(to_vec_named(&serde_json::json!({"ok":false,"error":"unknown cmd"}))?, 0)?;
            }
        }
    }
}
