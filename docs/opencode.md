# OpenCode Installation

## Quick Install

```sh
# macOS (Homebrew)
brew install opencode

# Linux (install script)
curl -fsSL https://opencode.dev/install.sh | sh

# Windows (Scoop)
scoop install opencode

# Or download directly from: https://opencode.dev/download
```

## Verify Installation

```sh
opencode --version
```

## Configuration

OpenCode stores config in `~/.config/opencode/`. Key files:

- `opencode.json` — Main configuration (providers, models, keybinds, etc.)
- `agents/` — Custom agent definitions
- `commands/` — Custom slash commands
- `skills/` — Custom skills

## Recommended Models

For this project, the following models work well with OpenCode:

| Model | Provider | Strengths |
|-------|----------|-----------|
| **Nemotron 3 Ultra** | NVIDIA | Excellent reasoning, coding, and analysis |
| **Hy4** | Hyperbolic | Strong coding, good context handling |
| **Kimi K3** | Moonshot | Long context, strong multilingual support |

Add to your `opencode.json`:

```json
{
  "providers": {
    "nvidia": {
      "api_key": "${NVIDIA_API_KEY}",
      "base_url": "https://integrate.api.nvidia.com/v1"
    },
    "hyperbolic": {
      "api_key": "${HYPERBOLIC_API_KEY}",
      "base_url": "https://api.hyperbolic.xyz/v1"
    },
    "moonshot": {
      "api_key": "${MOONSHOT_API_KEY}",
      "base_url": "https://api.moonshot.ai/v1"
    }
  },
  "models": {
    "default": "nvidia/nemotron-3-ultra",
    "coding": "hyperbolic/hy4",
    "long-context": "moonshot/kimi-k3"
  }
}
```

## Running with This Project

```sh
# From project root
opencode

# Or specify a model
opencode -m nvidia/nemotron-3-ultra
```

## Useful Commands

| Command | Description |
|---------|-------------|
| `opencode` | Start TUI |
| `opencode -c` | Continue last session |
| `opencode -m <model>` | Override default model |
| `opencode --help` | Show all options |

## Resources

- **Website**: https://opencode.dev
- **Documentation**: https://opencode.dev/docs
- **GitHub**: https://github.com/opencode-ai/opencode
- **Discord**: https://discord.gg/opencode