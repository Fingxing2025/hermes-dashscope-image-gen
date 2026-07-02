# Hermes DashScope Image Gen

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Hermes Plugin](https://img.shields.io/badge/Hermes-Plugin-7c3aed.svg)](https://github.com/NousResearch/hermes-agent)

> [中文文档 →](README_zh.md)

A native DashScope Qwen-Image generation backend plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
Call Alibaba Cloud's Qwen-Image models directly — no FAL.ai or other intermediaries required.

## Why This Plugin?

Hermes ships with image-gen backends for FAL.ai, OpenAI (DALL-E), xAI, and Krea — but not DashScope.
This plugin fills that gap, letting you use Qwen-Image models (which excel at **Chinese text rendering**,
complex layouts, and multi-line typography) directly through your existing DashScope API key.

## Supported Models

| Model ID | Description | Speed |
|----------|-------------|-------|
| `qwen-image-2.0-pro` | Best quality. Complex text rendering, multi-line layouts, 1–6 images per call. **(recommended)** | ~15s |
| `qwen-image-2.0` | Accelerated variant. Balanced speed and quality. | ~10s |
| `qwen-image-max` | Highest photorealism. Fewer AI artifacts, natural look. | ~20s |
| `qwen-image-plus` | Diverse artistic styles, good text rendering. | ~12s |

## Installation

### Option 1: pip install

```bash
pip install git+https://github.com/Fingxing2025/hermes-dashscope-image-gen.git
```

### Option 2: Clone + editable install

```bash
git clone https://github.com/Fingxing2025/hermes-dashscope-image-gen.git
cd hermes-dashscope-image-gen
pip install -e .
```

Then enable the plugin:

```bash
hermes plugins enable image_gen/dashscope
```

### Option 3: Copy files directly (no install)

Copy the two files into your Hermes plugins directory:

```bash
mkdir -p ~/.hermes/plugins/image_gen/dashscope/
cp hermes_dashscope_image_gen/plugin.yaml ~/.hermes/plugins/image_gen/dashscope/
cp hermes_dashscope_image_gen/__init__.py ~/.hermes/plugins/image_gen/dashscope/
hermes plugins enable image_gen/dashscope
```

## Configuration

### 1. Set your API key

Add to `~/.hermes/.env`:

```bash
DASHSCOPE_API_KEY=sk-your-api-key
```

Get a key at: https://bailian.console.aliyun.com/?apiKey=1

### 2. Configure image_gen

Add to `~/.hermes/config.yaml`:

```yaml
image_gen:
  provider: dashscope
  model: qwen-image-2.0-pro
  base_url: https://dashscope.aliyuncs.com/compatible-mode/v1

plugins:
  enabled:
    - image_gen/dashscope
```

> **Important:** `base_url` uses DashScope's OpenAI-compatible endpoint (the same one used for LLM chat).
> The plugin auto-strips `/compatible-mode/v1` and routes to the native image API at
> `https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation`.

### 3. International users

If using DashScope's international endpoint, override via env var:

```bash
export DASHSCOPE_BASE_URL=https://dashscope-intl.aliyuncs.com/api/v1
```

## Usage

Once configured, use Hermes's `image_generate` tool as usual:

```
Generate a landscape of blue sky and white clouds, photorealistic style
```

Or test via CLI:

```bash
hermes chat -q "Generate a cute cat sitting on a desk" --yolo -t image_gen
```

Generated images are saved to `~/.hermes/cache/images/`.

## How It Works

### Architecture

Hermes uses a plugin-based `ImageGenProvider` architecture. Each backend implements a subclass:

```
plugins/image_gen/<name>/
├── plugin.yaml    # metadata: name, kind, required env vars
└── __init__.py    # ImageGenProvider subclass + register() entrypoint
```

### Endpoint Resolution (the tricky part)

DashScope has **two separate API surfaces**:

| Surface | Path | Used for |
|---------|------|----------|
| OpenAI-compatible | `/compatible-mode/v1/chat/completions` | LLM text chat |
| Native API | `/api/v1/services/aigc/multimodal-generation/generation` | Image generation |

The user's `image_gen.base_url` config typically points at the compatible-mode endpoint
(because that's what's configured for LLM chat). The plugin detects and strips the
`/compatible-mode/v1` suffix, then attaches the native image API path:

```
User config:  https://dashscope.aliyuncs.com/compatible-mode/v1
                    ↓ strip /compatible-mode/v1
              https://dashscope.aliyuncs.com
                    ↓ append /api/v1/services/aigc/multimodal-generation/generation
Final URL:    https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation
```

### API Request Format

DashScope's native multimodal-generation API uses a different request shape than
OpenAI's images API:

```json
{
  "model": "qwen-image-2.0-pro",
  "input": {
    "messages": [{
      "role": "user",
      "content": [{ "text": "your prompt here" }]
    }]
  },
  "parameters": {
    "size": "2048*2048",
    "n": 1,
    "prompt_extend": true,
    "watermark": false
  }
}
```

Note: dimensions use `*` (e.g. `2048*2048`) — not `x` as in OpenAI's format.

### Response & Caching

DashScope returns a **temporary URL** that expires after 24 hours:

```json
{
  "output": {
    "choices": [{
      "message": {
        "content": [{ "image": "https://dashscope-result-sh.oss-.../xxx.png" }]
      }
    }]
  }
}
```

The plugin downloads the image immediately and caches it locally under
`~/.hermes/cache/images/`, so the file remains accessible even after the URL expires.

### Size Mapping

Different model families support different resolution ranges:

| Aspect Ratio | qwen-image-2.0-pro / 2.0 | qwen-image-max / plus |
|-------------|--------------------------|----------------------|
| landscape (16:9) | 2688×1536 | 1664×928 |
| square (1:1) | 2048×2048 | 1328×1328 |
| portrait (9:16) | 1536×2688 | 928×1664 |

## Project Structure

```
hermes-dashscope-image-gen/
├── hermes_dashscope_image_gen/
│   ├── __init__.py        # ImageGenProvider implementation (~470 lines)
│   └── plugin.yaml        # Hermes plugin metadata
├── pyproject.toml
├── LICENSE                # MIT
└── README.md
```

## Contributing to Hermes

This plugin is designed to be submitted as a PR to the main Hermes repo.
To contribute:

1. Fork [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
2. Copy `hermes_dashscope_image_gen/` into `plugins/image_gen/dashscope/`
3. Submit a PR with commit type `feat:`

## License

MIT — see [LICENSE](LICENSE).
