/**
 * platform.ts — OS-specific shims for the Nokido supervisor.
 *
 * Step 2 of the portable-supervisor migration (docs/portable_supervisor_plan.md).
 * Isolates the few OS-dependent operations so supervisor.ts stays
 * OS-agnostic. Adding an OS = add a branch here.
 */

const OS = Deno.build.os; // "windows" | "linux" | "darwin"

/** Physical RAM usage as a percentage (0-100). 0 on failure. */
export async function memUsagePct(): Promise<number> {
  try {
    if (OS === "windows") {
      // SANS SOUS-PROCESSUS D'ABORD (2026-09-24). Le `powershell` asynchrone lisait
      // son pipe sur le pool bloquant ; sature, la promesse ne se resolvait jamais
      // et la boucle de ressources du superviseur restait figee (ni vitalite, ni
      // regulation RAM). GlobalMemoryStatusEx via Deno : total/available en octets.
      // Acces optionnel type : la version de Deno n'est pas lisible depuis le hub,
      // l'API peut etre absente ou instable — compile et tourne dans les deux cas.
      // 2026-09-25 : ce calcul direct sur `available` a rendu 100.0 % EXACTEMENT chaque minute
      // depuis le 24/09 20h (journal du superviseur, ~1200 lectures) pendant que psutil mesurait
      // 52 % : sous Windows, Deno range la memoire disponible dans `free` et laisse `available`
      // a 0. La rafale RAM endormait alors TOUS les non-essentiels 5 min apres leur reveil.
      // Donc : `available`, sinon `free` ; et une lecture saturee (>= 99.5) ou hors bornes n'est
      // pas crue seule -- elle est recoupee par la voie synchrone ci-dessous.
      // NR : tests/nr/test_capteur_ram_superviseur_nr.py.
      try {
        const d = Deno as unknown as {
          systemMemoryInfo?: () => { total: number; available: number; free: number };
        };
        if (typeof d.systemMemoryInfo === "function") {
          const m = d.systemMemoryInfo();
          const dispo = m.available > 0 ? m.available : m.free;
          if (m.total > 0 && dispo > 0) {
            const pct = (1 - dispo / m.total) * 100;
            if (pct > 0 && pct < 99.5) return pct;
          }
        }
      } catch {
        // API absente ou non stable dans ce Deno : repli ci-dessous, jamais 0 muet.
      }
      const { stdout } = new Deno.Command("powershell", {
        args: [
          "-NoProfile",
          "-Command",
          // Both metrics in KB. FreePhysicalMemory (OS) was wrongly divided by
          // TotalPhysicalMemory (ComputerSystem, in BYTES) → freePct≈0 →
          // memUsagePct≈100% perma → supervisor slept all non-essentials.
          "(Get-CimInstance Win32_OperatingSystem | Select -Expand " +
          "FreePhysicalMemory) / (Get-CimInstance Win32_OperatingSystem | " +
          "Select -Expand TotalVisibleMemorySize) * 100",
        ],
        stdout: "piped",
        stderr: "piped",
      }).outputSync();
      const freePct = parseFloat(new TextDecoder().decode(stdout).trim());
      return Number.isFinite(freePct) ? 100 - freePct : 0;
    }

    if (OS === "linux") {
      const txt = await Deno.readTextFile("/proc/meminfo");
      const kb = (key: string) => {
        const m = txt.match(new RegExp(`^${key}:\\s+(\\d+)`, "m"));
        return m ? parseInt(m[1], 10) : 0;
      };
      const total = kb("MemTotal");
      const avail = kb("MemAvailable");
      return total > 0 ? (1 - avail / total) * 100 : 0;
    }

    if (OS === "darwin") {
      const totalOut = await new Deno.Command("sysctl", {
        args: ["-n", "hw.memsize"],
        stdout: "piped",
      }).output();
      const total = parseInt(
        new TextDecoder().decode(totalOut.stdout).trim(),
        10,
      );
      const vmOut = await new Deno.Command("vm_stat", { stdout: "piped" })
        .output();
      const vm = new TextDecoder().decode(vmOut.stdout);
      const pages = (re: RegExp) => parseInt(vm.match(re)?.[1] ?? "0", 10);
      const PAGE = 4096;
      const avail =
        (pages(/Pages free:\s+(\d+)/) + pages(/Pages inactive:\s+(\d+)/)) *
        PAGE;
      return total > 0 ? (1 - avail / total) * 100 : 0;
    }

    return 0;
  } catch {
    return 0;
  }
}

/** True when running on Windows (for the rare branch that still needs it). */
export function isWindows(): boolean {
  return OS === "windows";
}

if (import.meta.main) {
  console.log(`os=${OS}  memUsagePct=${(await memUsagePct()).toFixed(1)}%`);
}
