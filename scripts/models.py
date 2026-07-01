"""
Model tier registry - the single place that maps each job to a model.
Prompts reference tiers by name (flagship / mid / cheap / vision / ocr / image /
embed); swapping a model is a one-line edit here, no other changes.

Defaults target OpenAI. To use any OpenAI-compatible provider (z.ai, DeepSeek,
a local server, etc.), change the endpoint URLs and API_KEY_ENV below; the tool
code does not change. Auth keys come from your env file (AGENT_ENV_FILE) or the
environment.
"""

# Chat / reasoning
FLAGSHIP = "gpt-4o"          # reviews, briefings, user-facing replies
MID      = "gpt-4o-mini"    # digest assembly, classification
CHEAP    = "gpt-4o-mini"    # routing, structured writes, parsing

# Multimodal
VISION    = "gpt-4o"                 # image analysis
VISION_HQ = "gpt-4o"                 # same tier; a hook for a higher-quality swap
VIDEO     = "gpt-4o"                 # NOTE: video needs a video-capable model/provider;
                                     # OpenAI chat does not accept video input (point this
                                     # and CHAT_URL at e.g. Gemini or z.ai GLM-5V for video)
OCR       = "gpt-4o"                 # OCR via a vision prompt
IMAGE_GEN = "gpt-image-1"            # text -> image

# Embeddings
EMBED     = "text-embedding-3-small"
EMBED_DIM = 1536

# Provider endpoints + the env var that authenticates them. Defaults: OpenAI.
CHAT_URL    = "https://api.openai.com/v1/chat/completions"
IMAGE_URL   = "https://api.openai.com/v1/images/generations"
EMBED_URL   = "https://api.openai.com/v1/embeddings"
API_KEY_ENV = "OPENAI_API_KEY"

# --- Alternative providers (all OpenAI-compatible for chat). To switch, e.g.:
#   z.ai:     CHAT_URL = "https://api.z.ai/api/paas/v4/chat/completions"; API_KEY_ENV = "GLM_API_KEY"
#   DeepSeek: CHAT_URL = "https://api.deepseek.com/v1/chat/completions";  API_KEY_ENV = "DEEPSEEK_API_KEY"

TIERS = {
    "flagship":  FLAGSHIP,
    "mid":       MID,
    "cheap":     CHEAP,
    "vision":    VISION,
    "vision_hq": VISION_HQ,
    "video":     VIDEO,
    "ocr":       OCR,
    "image":     IMAGE_GEN,
    "embed":     EMBED,
}
