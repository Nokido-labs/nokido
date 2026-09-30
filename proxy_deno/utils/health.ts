/**
 * Fast-Fail : Ping TCP ultra-rapide (< 50ms)
 */
export async function isServiceAlive(port: number, hostname = "127.0.0.1"): Promise<boolean> {
  try {
    const conn = await Deno.connect({ port, hostname });
    conn.close();
    return true;
  } catch {
    return false;
  }
}
