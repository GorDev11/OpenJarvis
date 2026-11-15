# Windows network diagnostics in OpenJarvis Desktop

The Desktop Chat's local Ollama model is not a system administrator by itself.
The default server chat uses a tool-capable `orchestrator`, but tools must be
registered and granted. The opt-in `network_diagnostics` tool provides a
read-only snapshot on the **user's own Windows PC**.

## What the diagnostic can and cannot do

It can report connected adapters and their nominal link speed, IPv4 addresses,
gateway and DNS configuration, cached local neighbor entries, DNS resolution
for `example.com`, and a bounded TCP connection attempt to `1.1.1.1:443`.
It uses fixed PowerShell read operations only; no admin rights or configuration
changes. Timeouts and output lengths are bounded.

An ARP/neighbor table is **not** a router DHCP client list and cannot discover
all connected devices; it lists only devices recently observed by Windows.
LinkSpeed is **not** measured download/upload throughput. A failed public probe
can also reflect filtering rather than a broken network. Access to the router
administration page would require separate authorized access, not this tool.
Never present guessed hostnames, speeds or repairs as measured results.

## Enable for Desktop Chat

The feature branch includes this tool in the local server's default tool set,
but user-defined `tools.enabled` overrides the defaults. Make sure
`~/.openjarvis/config.toml` has the following values in its **existing**
sections (do not append duplicate TOML section headers):

```toml
[server]
agent = "orchestrator"

[tools]
enabled = "think,calculator,web_search,network_diagnostics"
```

The tool only becomes available after restarting the Python backend/Desktop.
If the Desktop runs a different checkout than the updated one, it will not see
the new tool. Do not edit `~/.openjarvis/config.toml` from this repository; it
is a machine-local setting.

Test the tool directly on Windows without an AI model:

```powershell
cd "$env:USERPROFILE\OpenJarvis"
.\.venv\Scripts\python.exe -c "from openjarvis.tools.network_diagnostics import NetworkDiagnosticsTool; r=NetworkDiagnosticsTool().execute(); print(r.content)"
```

It returns JSON, or an explicit failure. In Chat, ask:
"Ստուգիր իմ Windows համակարգչի ցանցը network_diagnostics գործիքով։
Տուր IP, gateway, DNS, կապի արդյունքը և հայտնաբերված հարևան սարքերը։
Չփոխես ոչ մի կարգավորում։ Եթե գործիք չես կանչել, հստակ ասա։"

If the Chat returns text without actually calling the tool, do not mistake
that text for a scan. Small models (for example Qwen3.5 4B) do not always
use tools reliably. A larger locally downloaded model may do better, at the
cost of more RAM/VRAM and slower inference. Check the Chat trace/logs for
a tool invocation before trusting any network claims.
