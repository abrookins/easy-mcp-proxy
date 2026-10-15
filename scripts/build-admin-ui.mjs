import { build } from "esbuild";
import { readFile, writeFile } from "node:fs/promises";
const directory = new URL("../mcp_proxy/admin_ui/", import.meta.url);
const result = await build({entryPoints:[new URL("embedded-entry.js", directory).pathname],bundle:true,write:false,format:"esm",target:"es2022",minify:true});
const script = result.outputFiles[0].text.replaceAll("</script", "<\\/script");
const css = await readFile(new URL("style.css", directory),"utf8");
const html = (await readFile(new URL("index.html", directory),"utf8"))
  .replace('<link rel="stylesheet" href="/config/assets/style.css">',`<style>${css}</style>`)
  .replace('<script src="/config/assets/app.js" defer></script>',"")
  .replace('<p id="message"', '<button id="browser-link" class="secondary" hidden>Open browser for credentials</button><p id="message"')
  .replace('To rotate a credential, replace its reference with the new value.', 'Use the browser to enter or rotate credentials; embedded tools reject inline secrets.')
  .replace('</body>',()=>`<script type="module">${script}</script></body>`);
await writeFile(new URL("embedded.html",directory),html);
console.log(`Built embedded admin UI (${Buffer.byteLength(html)} bytes).`);
