/**
 * service_loader_test.ts -- le NOUVEAU chargeur execute contre le VRAI services.toml (2026-10-08).
 *
 * Joue par `deno test -A proxy_deno/core/service_loader_test.ts` dans le job `gates` de la CI du poste de reference
 * (ci-selfhosted.yml, compte owner : le seul qui puisse lancer deno), et sur les VM du test d'installation. Ce qui est
 * prouve AVANT tout redemarrage du superviseur :
 *   1. sur le poste de reference (aucun %NOM% dans [vars], aucun config/vars.local.toml), le chargeur rend EXACTEMENT
 *      l'ancienne resolution `${CLE}` -> [vars] pour chaque service : le redemarrage ne change aucune commande ;
 *   2. le fichier machine passe par-dessus [vars], `%NOM%` est developpe depuis l'environnement, et un %NOM% inconnu
 *      reste VISIBLE sans casser le chargement.
 */
import { parse } from "https://deno.land/std@0.224.0/toml/mod.ts";
import { dirname, fromFileUrl } from "https://deno.land/std@0.224.0/path/mod.ts";
import { defaultTomlPath, loadServices, resoudreVars } from "./service_loader.ts";

const ROOT = fromFileUrl(new URL("../../", import.meta.url)).replace(/[\\/]$/, "");
const PROXY_DIR = fromFileUrl(new URL("../", import.meta.url)).replace(/[\\/]$/, "");

function naif(v: unknown, vars: Record<string, string>): string {
  return String(v ?? "").replace(/\$\{(\w+)\}/g, (m, k) => vars[k] ?? m);
}

function verifier(cond: boolean, msg: string): void {
  if (!cond) throw new Error(msg);
}

Deno.test("poste de reference : le nouveau chargeur rend exactement l'ancienne resolution", () => {
  // deno-lint-ignore no-explicit-any
  const doc = parse(Deno.readTextFileSync(defaultTomlPath())) as any;
  const pourcent = Object.values(doc.vars ?? {}).some((v) => String(v).includes("%"));
  let local = false;
  try {
    Deno.statSync(`${ROOT}/config/vars.local.toml`);
    local = true;
  } catch {
    local = false;
  }
  if (pourcent || local) {
    console.log(
      "[test] cette machine n'est PAS le poste de reference (%NOM% ou fichier machine) : " +
        "equivalence non applicable ici -- c'est DIT, ce n'est pas un succes",
    );
    return;
  }
  const rv = { ROOT, PROXY_DIR };
  const vars: Record<string, string> = { ...(doc.vars ?? {}), ...rv };
  const nouveaux = loadServices(defaultTomlPath(), rv);
  verifier(nouveaux !== null, "le chargeur a rendu null sur le services.toml reel");
  const bruts = doc.service ?? [];
  verifier(nouveaux!.length === bruts.length, `${bruts.length} services declares, ${nouveaux!.length} charges`);
  bruts.forEach((s: Record<string, unknown>, i: number) => {
    const n = nouveaux![i];
    verifier(n.name === String(s.name), `ordre perdu au rang ${i}`);
    verifier(n.cmd === naif(s.cmd, vars), `${n.name}: cmd ${naif(s.cmd, vars)} -> ${n.cmd}`);
    const args = Array.isArray(s.args) ? s.args.map((a: unknown) => naif(a, vars)) : [];
    verifier(JSON.stringify(n.args) === JSON.stringify(args), `${n.name}: arguments changes`);
    verifier(n.cwd === naif(s.cwd ?? ".", vars), `${n.name}: dossier ${naif(s.cwd ?? ".", vars)} -> ${n.cwd}`);
  });
  console.log(`[test] ${bruts.length} services : commandes, arguments et dossiers IDENTIQUES a l'ancienne resolution`);
  const pyResolu = resoudreVars(defaultTomlPath(), { ROOT })?.PYTHON;
  verifier(pyResolu === String(doc.vars.PYTHON), `interpreteur runAs change : ${doc.vars.PYTHON} -> ${pyResolu}`);
  console.log("[test] interpreteur des lanceurs runAs IDENTIQUE a l'ancien litteral du superviseur");
});

Deno.test("service propre au poste : non demarre ou son dossier manque, demarre ou il existe", () => {
  const dir = Deno.makeTempDirSync();
  const toml = (cwd: string) =>
    ["[[service]]", 'name = "R"', "wave = 1", 'cmd = "runner"', `cwd = "${cwd}"`, "propre_au_poste = true", ""]
      .join("\n");
  Deno.writeTextFileSync(`${dir}/absent.toml`, toml(`${dir}/inexistant_runner`.replaceAll("\\", "/")));
  Deno.writeTextFileSync(`${dir}/present.toml`, toml(dir.replaceAll("\\", "/")));
  const absent = loadServices(`${dir}/absent.toml`, { ROOT: dir });
  const present = loadServices(`${dir}/present.toml`, { ROOT: dir });
  verifier(absent !== null && absent[0].disabled === true, "un runner d'une autre machine ne doit pas demarrer");
  verifier(present !== null && !present[0].disabled, "sur son poste, le runner demarre");
});

Deno.test("lanceurs runAs et racine generisee : PYTHON du fichier machine, %NOKIDO_ROOT% developpe", () => {
  Deno.env.delete("NOKIDO_ROOT");
  Deno.env.delete("NOKIDO_WORKSPACE");
  const dir = Deno.makeTempDirSync();
  Deno.mkdirSync(`${dir}/config`);
  Deno.writeTextFileSync(
    `${dir}/services.toml`,
    [
      "[vars]",
      'PYTHON = "%USERPROFILE%/miniforge3/python.exe"',
      "",
      "[[service]]",
      'name = "C"',
      "wave = 1",
      'cmd = "${PYTHON}"',
      'cwd = "%NOKIDO_ROOT%"',
      'args = ["%NOKIDO_WORKSPACE%/voisin"]',
      "",
    ].join("\n"),
  );
  Deno.writeTextFileSync(`${dir}/config/vars.local.toml`, '[vars]\nPYTHON = "/machine/python"\n');
  verifier(resoudreVars(`${dir}/services.toml`, { ROOT: dir })?.PYTHON === "/machine/python",
    "le superviseur ne prendrait pas l'interpreteur de la machine pour ses lanceurs runAs");
  const s = loadServices(`${dir}/services.toml`, { ROOT: dir });
  verifier(s !== null && s.length === 1, "le chargement a casse");
  verifier(s![0].cwd === dir, `%NOKIDO_ROOT% non developpe : ${s![0].cwd}`);
  verifier(s![0].args[0] === `${dirname(dir)}/voisin`, `%NOKIDO_WORKSPACE% non developpe : ${s![0].args[0]}`);
});

Deno.test("fichier machine par-dessus [vars], %NOM% developpe, %NOM% inconnu visible", () => {
  const dir = Deno.makeTempDirSync();
  Deno.mkdirSync(`${dir}/config`);
  Deno.writeTextFileSync(
    `${dir}/services.toml`,
    [
      "[vars]",
      'PYTHON = "C:/inexistant/python.exe"',
      'OUTIL = "%NOKIDO_TEST_DOSSIER%/outil"',
      'PERDU = "%NOKIDO_TEST_ABSENT_XYZ%/x"',
      "",
      "[[service]]",
      'name = "A"',
      "wave = 1",
      'cmd = "${PYTHON}"',
      'args = ["${OUTIL}"]',
      "",
      "[[service]]",
      'name = "B"',
      "wave = 1",
      'cmd = "${PERDU}"',
      "",
    ].join("\n"),
  );
  Deno.writeTextFileSync(`${dir}/config/vars.local.toml`, '[vars]\nPYTHON = "/machine/python"\n');
  Deno.env.set("NOKIDO_TEST_DOSSIER", "/opt/test");
  const s = loadServices(`${dir}/services.toml`, { ROOT: dir });
  verifier(s !== null && s.length === 2, "le chargement a casse");
  verifier(s![0].cmd === "/machine/python", `fichier machine ignore : ${s![0].cmd}`);
  verifier(s![0].args[0] === "/opt/test/outil", `%NOM% non developpe : ${s![0].args[0]}`);
  verifier(s![1].cmd.includes("%NOKIDO_TEST_ABSENT_XYZ%"), "un %NOM% inconnu doit rester VISIBLE, jamais vide");
});
