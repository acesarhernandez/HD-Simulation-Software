# Windows LLM Host Setup

This guide is for the optional `v2` LLM path.

Use it when:

- the simulator stays on your homelab
- your Windows gaming PC runs Ollama
- the simulator calls that PC over the network only when LLM mode is enabled

## What This Does

The simulator can work in two modes:

- **Without LLM:** behaves like `v1` using rule-based replies
- **With LLM:** uses Ollama for more natural end-user responses, while still falling back to rule-based behavior if Ollama is unavailable

Wake-on-LAN is optional. It only exists so the homelab can try to wake the Windows PC before LLM use.

## Part 1: Install Ollama On Windows

1. Download and install Ollama from the official site:
   - [https://ollama.com/download/windows](https://ollama.com/download/windows)
2. After installation, open PowerShell.
3. Pull a model you want to use. Example:

```powershell
ollama pull llama3.1:8b
```

4. Start Ollama if it is not already running:

```powershell
ollama serve
```

5. Test locally on the Windows PC:

```powershell
ollama run llama3.1:8b
```

If that works, Ollama is installed correctly.

## Part 2: Confirm The Ollama API

By default, Ollama listens on port `11434`.

On the Windows PC, test:

```powershell
curl http://127.0.0.1:11434/api/tags
```

You should get JSON back showing installed models.

Then test from another machine on your network using the Windows PC's reachable IP:

```bash
curl http://<WINDOWS_PC_IP>:11434/api/tags
```

If the remote request fails, check:

- Windows Defender Firewall
- any third-party firewall rules
- whether the PC is on the same network/Tailscale path you expect

## Part 3: Enable Wake-on-LAN

Wake-on-LAN has to work at the hardware, firmware, and Windows levels.

### BIOS / UEFI

In your motherboard firmware settings, enable the feature usually named something like:

- `Wake on LAN`
- `Power On By PCI-E`
- `Resume By LAN`
- `Wake From S5`

The exact wording varies by motherboard vendor.

### Windows Network Adapter

1. Open `Device Manager`
2. Expand `Network adapters`
3. Open your active Ethernet adapter
4. Under `Power Management`:
   - enable `Allow this device to wake the computer`
   - enable `Only allow a magic packet to wake the computer`
5. Under `Advanced`, enable settings such as:
   - `Wake on Magic Packet`
   - `Shutdown Wake-On-Lan`
   - any similar wake options your adapter exposes

Wake-on-LAN is most reliable over wired Ethernet. Wi-Fi support depends heavily on hardware and is often limited.

### Windows Power Settings

If wake from a powered-down state is inconsistent:

- turn off `Fast Startup`
- verify the PC still receives standby power while "off"

## Part 4: Find The MAC Address

On the Windows PC:

```powershell
ipconfig /all
```

Find the active network adapter and copy its physical address.

Example:

```text
AA-BB-CC-DD-EE-FF
```

Use that value in the simulator config as:

```env
SIM_LLM_HOST_MAC=AA:BB:CC:DD:EE:FF
```

## Part 5: Configure The Simulator

In the simulator `.env` on the machine running the app:

```env
SIM_RESPONSE_ENGINE=ollama
SIM_OLLAMA_URL=http://<WINDOWS_PC_IP>:11434
SIM_OLLAMA_MODEL=llama3.1:8b
SIM_OLLAMA_FALLBACK_TO_RULE_BASED=true

SIM_LLM_HOST_LABEL=Gaming PC
SIM_LLM_HOST_WOL_ENABLED=true
SIM_LLM_HOST_MAC=AA:BB:CC:DD:EE:FF
SIM_LLM_HOST_WOL_BROADCAST_IP=255.255.255.255
SIM_LLM_HOST_WOL_PORT=9
```

If you want to keep `v1` behavior with no LLM, use:

```env
SIM_RESPONSE_ENGINE=rule_based
SIM_LLM_HOST_WOL_ENABLED=false
```

## Part 6: Test In Order

Test in this order so you know exactly what is failing if something breaks:

1. Confirm Ollama works locally on the Windows PC
2. Confirm the Ollama API works locally (`/api/tags`)
3. Confirm the Ollama API works remotely from another machine
4. Confirm a Wake-on-LAN packet can wake the PC
5. Point the simulator at the Windows PC
6. Switch `SIM_RESPONSE_ENGINE=ollama`
7. Verify the simulator still falls back safely if Ollama is offline

## Useful Simulator Endpoints

- `GET /v1/runtime/response-engine`
  - shows whether the app is using rule-based mode, live Ollama, or fallback mode
- `POST /v1/runtime/wake-llm-host`
  - sends the Wake-on-LAN magic packet if configured

## Notes

- The simulator should still remain usable without the LLM.
- The LLM is an enhancement layer, not a dependency.
- If Ollama is down or sleeping, `v2` can fall back to `v1` style rule-based replies.
