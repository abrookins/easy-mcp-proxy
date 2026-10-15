import { App } from "@modelcontextprotocol/ext-apps";

const app = new App({name:"MCP Proxy configuration",version:"1.0.0"},{});
const message = document.getElementById("message");
message.textContent = "Connecting to the host. If embedded UI is unavailable, open the browser_url from proxy_status.";
document.getElementById("logout").hidden = true;
app.ontoolresult = () => {};
app.onhostcontextchanged = context => {
  if (context.theme) document.documentElement.style.colorScheme = context.theme;
};
window.proxyAdminTransport = async (action, payload) => {
  const result = await app.callServerTool({name:`proxy_${action}`,arguments:payload || {}});
  if (result.isError) throw new Error(result.content?.find(item => item.type === "text")?.text || "Operation failed.");
  const value = result.structuredContent || JSON.parse(result.content.find(item => item.type === "text").text);
  if (action === "status" && value.browser_url) {
    const button = document.getElementById("browser-link");
    button.hidden = false;
    button.onclick = () => app.openLink({url:value.browser_url});
  }
  return value;
};
try {
  await app.connect();
  await import("./app.js");
} catch {
  message.textContent = "This host could not connect the embedded screen. Use the browser_url returned by proxy_status, or the text administration tools.";
}
