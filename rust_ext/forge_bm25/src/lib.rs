use pyo3::prelude::*;
use std::collections::HashMap;

/// BM25Okapi-compatible scorer — drop-in for rank_bm25.BM25Okapi
/// k1=1.5, b=0.75 (same defaults), epsilon=0.25 for floor IDF
#[pyclass]
struct BM25 {
    k1: f64,
    b: f64,
    avgdl: f64,
    doc_freqs: Vec<HashMap<String, usize>>,  // term → count per doc
    idf: HashMap<String, f64>,
    doc_len: Vec<usize>,
    corpus_size: usize,
}

#[pymethods]
impl BM25 {
    #[new]
    #[pyo3(signature = (corpus, k1=1.5, b=0.75, epsilon=0.25))]
    fn new(corpus: Vec<Vec<String>>, k1: f64, b: f64, epsilon: f64) -> Self {
        let corpus_size = corpus.len();
        let mut doc_freqs: Vec<HashMap<String, usize>> = Vec::with_capacity(corpus_size);
        let mut doc_len: Vec<usize> = Vec::with_capacity(corpus_size);
        let mut nd: HashMap<String, usize> = HashMap::new(); // doc freq per term

        let mut total_len: usize = 0;
        for doc in &corpus {
            let mut freq: HashMap<String, usize> = HashMap::new();
            for token in doc {
                *freq.entry(token.clone()).or_insert(0) += 1;
            }
            for term in freq.keys() {
                *nd.entry(term.clone()).or_insert(0) += 1;
            }
            total_len += doc.len();
            doc_len.push(doc.len());
            doc_freqs.push(freq);
        }

        let avgdl = if corpus_size > 0 {
            total_len as f64 / corpus_size as f64
        } else {
            1.0
        };

        // IDF with floor to avoid negative scores (rank_bm25 epsilon trick)
        let mut idf_vals: Vec<f64> = Vec::with_capacity(nd.len());
        let mut idf: HashMap<String, f64> = HashMap::with_capacity(nd.len());
        for (term, df) in &nd {
            let n = corpus_size as f64;
            let df = *df as f64;
            let v = ((n - df + 0.5) / (df + 0.5) + 1.0).ln();
            idf_vals.push(v);
            idf.insert(term.clone(), v);
        }

        // Apply epsilon floor (same as BM25Okapi)
        if !idf_vals.is_empty() {
            let avg_idf = idf_vals.iter().sum::<f64>() / idf_vals.len() as f64;
            let floor = epsilon * avg_idf;
            for v in idf.values_mut() {
                if *v < 0.0 {
                    *v = floor;
                }
            }
        }

        BM25 { k1, b, avgdl, doc_freqs, idf, doc_len, corpus_size }
    }

    /// get_scores(query: list[str]) -> list[float]  — same signature as rank_bm25
    fn get_scores(&self, query: Vec<String>) -> Vec<f64> {
        let mut scores = vec![0.0f64; self.corpus_size];
        for token in &query {
            let idf = match self.idf.get(token) {
                Some(&v) => v,
                None => continue,
            };
            for (i, freq_map) in self.doc_freqs.iter().enumerate() {
                let tf = *freq_map.get(token).unwrap_or(&0) as f64;
                if tf == 0.0 {
                    continue;
                }
                let dl = self.doc_len[i] as f64;
                let norm = self.k1 * (1.0 - self.b + self.b * dl / self.avgdl);
                scores[i] += idf * tf * (self.k1 + 1.0) / (tf + norm);
            }
        }
        scores
    }

    /// get_top_n(query, n) -> list[(score, doc_index)]  — bonus utility
    fn get_top_n(&self, query: Vec<String>, n: usize) -> Vec<(f64, usize)> {
        let scores = self.get_scores(query);
        let mut indexed: Vec<(f64, usize)> = scores.into_iter().enumerate()
            .map(|(i, s)| (s, i))
            .collect();
        indexed.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
        indexed.truncate(n);
        indexed
    }
}

#[pymodule]
fn forge_bm25(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<BM25>()?;
    Ok(())
}
