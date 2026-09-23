import os
import sys
import json
import base64
import hashlib
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


# ============================================================
# FAZL ULLAH AZAAD
# DAILY PERSONAL-BRAND SOCIAL MEDIA AUTOMATION
# ============================================================

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
BUFFER_API_KEY = os.environ.get("BUFFER_API_KEY")

if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY secret is missing.")

if not BUFFER_API_KEY:
    raise RuntimeError("BUFFER_API_KEY secret is missing.")


# ============================================================
# CONFIGURATION
# ============================================================

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_IMAGE_URL = "https://openrouter.ai/api/v1/images"
BUFFER_URL = "https://api.buffer.com"

TEXT_MODEL = "google/gemini-3.1-flash-lite"
IMAGE_MODEL = "bytedance-seed/seedream-4.5"

REPO_OWNER = "beneficial382-hash"
REPO_NAME = "social-media-automation"
BRANCH = "main"

ROOT = Path(".")
SITE_DIR = ROOT / "site"
MEDIA_DIR = SITE_DIR / "media"

HISTORY_FILE = ROOT / "content_history.json"
POST_FILE = ROOT / "post_data.json"
PENDING_FILE = ROOT / "pending_post.json"

TARGET_SERVICES = {
    "facebook",
    "instagram",
    "linkedin",
}

MAX_HISTORY_FOR_AI = 25
MAX_LOCAL_SIMILARITY_HISTORY = 100


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def today_string():
    return now_utc().strftime("%Y-%m-%d")


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


def read_json(path, default=None):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def normalize_text(text):
    text = str(text or "").lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def text_words(text):
    return set(normalize_text(text).split())


def similarity(a, b):
    a_words = text_words(a)
    b_words = text_words(b)

    if not a_words or not b_words:
        return 0.0

    intersection = len(a_words & b_words)
    union = len(a_words | b_words)

    return intersection / union if union else 0.0


def text_hash(text):
    return hashlib.sha256(
        normalize_text(text).encode("utf-8")
    ).hexdigest()


def safe_filename(text):
    text = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "-",
        str(text),
    )

    return text.strip("-_").lower()


def html_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ============================================================
# HISTORY
# ============================================================

def load_history():
    history = read_json(
        HISTORY_FILE,
        [],
    )

    if not isinstance(history, list):
        return []

    return history


def compact_history(history):
    result = []

    for item in history[-MAX_HISTORY_FOR_AI:]:
        result.append(
            {
                "date": item.get("date", ""),
                "theme": item.get("theme", ""),
                "caption": str(
                    item.get("caption", "")
                )[:700],
            }
        )

    return result


def all_previous_themes(history):
    themes = []

    for item in history:
        theme = str(
            item.get("theme", "")
        ).strip()

        if theme:
            themes.append(theme)

    return themes[-150:]


# ============================================================
# OPENROUTER CHAT
# ============================================================

def openrouter_chat(
    messages,
    temperature=0.8,
    max_tokens=3000,
):
    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
        "HTTP-Referer": (
            "https://beneficial382-hash.github.io/"
            "social-media-automation/"
        ),
        "X-Title": (
            "Fazl Ullah Azaad "
            "Daily Social Media Automation"
        ),
    }

    payload = {
        "model": TEXT_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    response = requests.post(
        OPENROUTER_CHAT_URL,
        headers=headers,
        json=payload,
        timeout=180,
    )

    if not response.ok:
        raise RuntimeError(
            "OpenRouter text request failed: "
            f"{response.status_code}\n"
            f"{response.text}"
        )

    data = response.json()

    try:
        content = (
            data["choices"][0]
            ["message"]
            ["content"]
        )
    except Exception:
        raise RuntimeError(
            "Unexpected OpenRouter response:\n"
            + json.dumps(
                data,
                indent=2,
            )[:5000]
        )

    if isinstance(content, list):
        parts = []

        for item in content:
            if (
                isinstance(item, dict)
                and item.get("type") == "text"
            ):
                parts.append(
                    item.get("text", "")
                )

        content = "\n".join(parts)

    return str(content).strip()


# ============================================================
# JSON PARSING
# ============================================================

def extract_json(text):
    text = str(text).strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        candidate = text[
            start:end + 1
        ]

        try:
            return json.loads(candidate)
        except Exception:
            pass

    raise RuntimeError(
        "AI did not return valid JSON:\n"
        + text[:5000]
    )


# ============================================================
# CONTENT VALIDATION
# ============================================================

def validate_content(data):
    required = [
        "theme",
        "caption",
        "description",
        "seo_keywords",
        "facebook_instagram_hashtags",
        "linkedin_hashtags",
        "image_count",
        "image_prompts",
    ]

    for key in required:
        if key not in data:
            raise RuntimeError(
                f"Generated content is missing '{key}'."
            )

    if not str(data["theme"]).strip():
        raise RuntimeError(
            "Theme is empty."
        )

    if not str(data["caption"]).strip():
        raise RuntimeError(
            "Caption is empty."
        )

    if not isinstance(
        data["image_count"],
        int,
    ):
        raise RuntimeError(
            "image_count must be an integer."
        )

    if data["image_count"] not in (1, 2):
        raise RuntimeError(
            "image_count must be 1 or 2."
        )

    if not isinstance(
        data["image_prompts"],
        list,
    ):
        raise RuntimeError(
            "image_prompts must be a list."
        )

    if len(data["image_prompts"]) != data["image_count"]:
        raise RuntimeError(
            "image_prompts count does not "
            "match image_count."
        )


# ============================================================
# GENERATE CONTENT
# ============================================================

def generate_content(history):
    previous_posts = compact_history(history)
    previous_themes = all_previous_themes(history)

    system_prompt = """
You are the professional personal-brand content strategist,
writer, and editor for Fazl Ullah Azaad.

Create ONE original social-media post about real life.

The writing must be:

- intelligent
- mature
- realistic
- meaningful
- practical
- authentic
- naturally motivational
- grammatically correct
- professionally written
- human-sounding

The post must NOT sound like generic AI motivational content.

Do not invent:
- achievements
- personal experiences
- conversations
- statistics
- studies
- research findings
- events
- quotations
- testimonials

Do not attribute quotations to famous people.

Do not use political persuasion.

Do not make exaggerated promises.

Avoid empty motivational clichés.

The central idea must be genuinely different from previous
posts.

Changing only the wording does NOT make a post original.

Changing only the example does NOT make a post original.

The new post must introduce a different lesson, perspective,
observation, or practical insight.

The post should normally work on Facebook, Instagram,
and LinkedIn.

IMAGE RULES:

Choose exactly 1 or exactly 2 images.

Use 2 only when two genuinely different visuals improve
the communication of the idea.

Otherwise choose 1.

Images must be:

- photorealistic
- cinematic
- professional
- realistic
- vertical 9:16
- suitable for a professional personal brand
- visually meaningful

Images must contain:

- NO text
- NO words
- NO letters
- NO logos
- NO watermark
- NO typography
- NO quotation written inside the image

The image should communicate the idea visually rather than
literally displaying the caption.

Return ONLY valid JSON.

Required structure:

{
  "theme": "short central idea",
  "caption": "complete social media caption",
  "description": "short description",
  "seo_keywords": ["keyword 1", "keyword 2"],
  "facebook_instagram_hashtags": ["#...", "#..."],
  "linkedin_hashtags": ["#...", "#..."],
  "image_count": 1,
  "image_prompts": [
    "complete image generation prompt"
  ]
}
"""

    user_prompt = f"""
Today's date:
{today_string()}

PREVIOUS POSTS:
{json.dumps(
    previous_posts,
    ensure_ascii=False,
    indent=2,
)}

PREVIOUS THEMES:
{json.dumps(
    previous_themes,
    ensure_ascii=False,
    indent=2,
)}

IMPORTANT:

Create something genuinely new.

The new post must be different from previous posts in:

1. central idea
2. lesson
3. perspective
4. wording
5. example

Do NOT simply rewrite an old post.

Do NOT reuse an old lesson with different words.

Do NOT produce a shallow variation of an old theme.

The content should feel like a thoughtful observation about
real life that a real person could naturally share.
"""

    raw = openrouter_chat(
        [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        temperature=0.9,
        max_tokens=3000,
    )

    data = extract_json(raw)

    validate_content(data)

    return data


# ============================================================
# LOCAL ORIGINALITY CHECK
# ============================================================

def local_originality_check(
    candidate,
    history,
):
    candidate_text = (
        candidate.get("theme", "")
        + " "
        + candidate.get("caption", "")
    )

    candidate_hash = text_hash(
        candidate_text
    )

    for item in history:
        old_text = (
            item.get("theme", "")
            + " "
            + item.get("caption", "")
        )

        if text_hash(old_text) == candidate_hash:
            return (
                False,
                "Exact duplicate detected.",
            )

    for item in history[
        -MAX_LOCAL_SIMILARITY_HISTORY:
    ]:
        old_text = (
            item.get("theme", "")
            + " "
            + item.get("caption", "")
        )

        score = similarity(
            candidate_text,
            old_text,
        )

        if score >= 0.72:
            return (
                False,
                "Too similar to a previous post "
                f"(similarity={score:.2f}).",
            )

    return (
        True,
        "Local originality check passed.",
    )


# ============================================================
# AI ORIGINALITY AUDIT
# ============================================================

def ai_originality_audit(
    candidate,
    history,
):
    prompt = f"""
You are a strict originality editor.

Determine whether the proposed post has a genuinely different
central idea from the previous posts.

PROPOSED POST:
{json.dumps(
    candidate,
    ensure_ascii=False,
    indent=2,
)}

PREVIOUS POSTS:
{json.dumps(
    compact_history(history),
    ensure_ascii=False,
    indent=2,
)}

Reject it if it:

- repeats the same lesson
- merely changes wording
- changes only the example
- expresses essentially the same idea from the same perspective
- is a generic variation of a previous post

Accept it only when the central insight is genuinely distinct.

Return ONLY:

{{
  "original": true,
  "reason": "short reason"
}}
"""

    raw = openrouter_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a strict originality auditor. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.1,
        max_tokens=500,
    )

    result = extract_json(raw)

    original = result.get(
        "original",
        False,
    )

    if isinstance(
        original,
        str,
    ):
        original = (
            original.lower() == "true"
        )

    return (
        bool(original),
        str(
            result.get(
                "reason",
                "",
            )
        ),
    )


# ============================================================
# IMAGE GENERATION
# ============================================================

def generate_image(
    prompt,
    output_path,
):
    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "resolution": "2K",
        "n": 1,
    }

    response = requests.post(
        OPENROUTER_IMAGE_URL,
        headers=headers,
        json=payload,
        timeout=300,
    )

    if not response.ok:
        raise RuntimeError(
            "OpenRouter image generation failed: "
            f"{response.status_code}\n"
            f"{response.text}"
        )

    data = response.json()

    try:
        image = data["data"][0]
        image_base64 = image["b64_json"]
    except Exception:
        raise RuntimeError(
            "OpenRouter did not return the expected "
            "image response:\n"
            + json.dumps(
                data,
                indent=2,
            )[:5000]
        )

    image_bytes = base64.b64decode(
        image_base64
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_bytes(
        image_bytes
    )

    if output_path.stat().st_size < 1000:
        raise RuntimeError(
            "Generated image appears invalid."
        )

    print(
        f"Image generated: {output_path}"
    )


# ============================================================
# GITHUB URL
# ============================================================

def github_raw_url(
    relative_path,
):
    relative = str(
        relative_path
    ).replace("\\", "/")

    return (
        "https://raw.githubusercontent.com/"
        f"{REPO_OWNER}/"
        f"{REPO_NAME}/"
        f"{BRANCH}/"
        f"{relative}"
    )


# ============================================================
# VERIFY PUBLIC MEDIA
# ============================================================

def verify_public_url(
    url,
    attempts=15,
):
    print(
        "Checking public image URL:"
    )
    print(url)

    for attempt in range(
        1,
        attempts + 1,
    ):
        try:
            response = requests.get(
                url,
                timeout=20,
                allow_redirects=True,
                stream=True,
            )

            content_type = (
                response.headers
                .get(
                    "content-type",
                    "",
                )
                .lower()
            )

            if (
                response.status_code == 200
                and content_type.startswith("image/")
            ):
                response.close()

                print(
                    "Public image verified."
                )

                return

            response.close()

        except requests.RequestException:
            pass

        print(
            f"Waiting for image "
            f"({attempt}/{attempts})..."
        )

        time.sleep(5)

    raise RuntimeError(
        "Public image URL could not be verified:\n"
        + url
    )


# ============================================================
# GITHUB COMMIT
# ============================================================

def git_commit_and_push(
    message,
    files,
):
    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "github-actions[bot]",
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]"
            "@users.noreply.github.com",
        ],
        check=True,
    )

    subprocess.run(
        ["git", "add"] + files,
        check=True,
    )

    check = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ]
    )

    if check.returncode == 0:
        print(
            "No changes to commit."
        )
        return

    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            message,
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "push",
            "origin",
            BRANCH,
        ],
        check=True,
    )

    print(
        "Changes pushed to GitHub."
    )


# ============================================================
# CREATE GITHUB PAGES SITE
# ============================================================

def create_site(
    post,
):
    SITE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    image_html = ""

    for url in post[
        "image_urls"
    ]:
        image_html += f"""
        <img
          src="{html_escape(url)}"
          alt="Daily visual"
          loading="lazy"
        >
        """

    all_hashtags = list(
        dict.fromkeys(
            post[
                "facebook_instagram_hashtags"
            ]
            +
            post[
                "linkedin_hashtags"
            ]
        )
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">

<meta
  name="viewport"
  content="width=device-width, initial-scale=1.0"
>

<title>
Fazl Ullah Azaad — Daily Post
</title>

<meta
  name="description"
  content="{html_escape(post['description'])}"
>

<style>

body {{
    margin: 0;
    padding: 30px 18px;
    background: #ffffff;
    color: #111111;
    font-family:
        Arial,
        Helvetica,
        sans-serif;
}}

main {{
    max-width: 850px;
    margin: 0 auto;
}}

.card {{
    border: 1px solid #dddddd;
    border-radius: 14px;
    padding: 25px;
}}

h1 {{
    margin-top: 0;
}}

.theme {{
    margin-top: 30px;
}}

.caption {{
    white-space: pre-wrap;
    line-height: 1.7;
    font-size: 18px;
}}

.images {{
    display: grid;
    gap: 18px;
    margin-top: 25px;
}}

.images img {{
    width: 100%;
    max-width: 500px;
    border-radius: 12px;
}}

.meta {{
    margin-top: 25px;
    font-size: 14px;
    line-height: 1.6;
}}

</style>
</head>

<body>

<main>

<div class="card">

<h1>
Fazl Ullah Azaad
</h1>

<p>
Daily Personal-Brand Content
</p>

<h2 class="theme">
{html_escape(post["theme"])}
</h2>

<div class="caption">
{html_escape(post["caption"])}
</div>

<div class="images">
{image_html}
</div>

<div class="meta">

<p>
<strong>SEO Keywords:</strong>
{html_escape(
    ", ".join(
        post["seo_keywords"]
    )
)}
</p>

<p>
<strong>Hashtags:</strong>
{html_escape(
    " ".join(all_hashtags)
)}
</p>

</div>

</div>

</main>

</body>
</html>
"""

    with (
        SITE_DIR / "index.html"
    ).open(
        "w",
        encoding="utf-8",
    ) as f:
        f.write(html)


# ============================================================
# GENERATE
# ============================================================

def generate():
    print("=" * 65)
    print(
        "FAZL ULLAH AZAAD "
        "DAILY CONTENT GENERATION"
    )
    print("=" * 65)

    history = load_history()

    print(
        f"Successful posts in history: "
        f"{len(history)}"
    )

    candidate = None

    for attempt in range(
        1,
        6,
    ):
        print(
            f"\nCreating candidate "
            f"{attempt}/5..."
        )

        candidate = generate_content(
            history
        )

        local_ok, local_reason = (
            local_originality_check(
                candidate,
                history,
            )
        )

        print(local_reason)

        if not local_ok:
            candidate = None
            continue

        audit_ok, audit_reason = (
            ai_originality_audit(
                candidate,
                history,
            )
        )

        print(
            "AI originality audit: "
            + audit_reason
        )

        if audit_ok:
            break

        candidate = None

    if candidate is None:
        raise RuntimeError(
            "Unable to generate a sufficiently "
            "original post after 5 attempts."
        )

    print("\nSelected theme:")
    print(candidate["theme"])

    print("\nCaption:")
    print(candidate["caption"])

    image_count = candidate[
        "image_count"
    ]

    date = today_string()

    MEDIA_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    image_urls = []
    image_files = []

    for index, prompt in enumerate(
        candidate["image_prompts"],
        start=1,
    ):
        filename = (
            f"{date}-"
            f"{safe_filename(candidate['theme'])[:50]}-"
            f"{index}.jpg"
        )

        output_path = (
            MEDIA_DIR / filename
        )

        print(
            f"\nGenerating image "
            f"{index}/{image_count}..."
        )

        generate_image(
            prompt,
            output_path,
        )

        relative_path = (
            output_path.relative_to(
                ROOT
            )
        )

        relative_url = str(
            relative_path
        ).replace(
            "\\",
            "/",
        )

        public_url = github_raw_url(
            relative_path
        )

        image_files.append(
            relative_url
        )

        image_urls.append(
            public_url
        )

    post = {
        "date": date,
        "generated_at_utc": (
            now_utc().isoformat()
        ),
        "author": (
            "Fazl Ullah Azaad"
        ),
        "theme": candidate["theme"],
        "caption": candidate["caption"],
        "description": candidate[
            "description"
        ],
        "seo_keywords": candidate[
            "seo_keywords"
        ],
        "facebook_instagram_hashtags": (
            candidate[
                "facebook_instagram_hashtags"
            ]
        ),
        "linkedin_hashtags": (
            candidate[
                "linkedin_hashtags"
            ]
        ),
        "image_count": image_count,
        "image_prompts": candidate[
            "image_prompts"
        ],
        "image_files": image_files,
        "image_urls": image_urls,
        "publication_status": (
            "pending"
        ),
    }

    write_json(
        POST_FILE,
        post,
    )

    write_json(
        PENDING_FILE,
        post,
    )

    create_site(post)

    git_commit_and_push(
        "Generate daily social media content",
        [
            "site",
            "post_data.json",
            "pending_post.json",
        ],
    )

    for url in image_urls:
        verify_public_url(url)

    print(
        "\nGeneration completed."
    )


# ============================================================
# BUFFER HELPERS
# ============================================================

def buffer_request(
    query,
):
    response = requests.post(
        BUFFER_URL,
        headers={
            "Authorization": (
                f"Bearer {BUFFER_API_KEY}"
            ),
            "Content-Type": (
                "application/json"
            ),
        },
        json={
            "query": query,
        },
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            "Buffer HTTP error "
            f"{response.status_code}:\n"
            f"{response.text}"
        )

    data = response.json()

    if data.get("errors"):
        raise RuntimeError(
            "Buffer GraphQL error:\n"
            + json.dumps(
                data["errors"],
                indent=2,
            )
        )

    return data


def get_buffer_channels():
    organization_query = """
    query GetOrganizations {
      account {
        organizations {
          id
          name
        }
      }
    }
    """

    data = buffer_request(
        organization_query
    )

    organizations = (
        data
        .get("data", {})
        .get("account", {})
        .get("organizations", [])
    )

    if not organizations:
        raise RuntimeError(
            "No Buffer organization found."
        )

    organization_id = (
        organizations[0]["id"]
    )

    channel_query = f"""
    query GetChannels {{
      channels(
        input: {{
          organizationId: "{organization_id}"
        }}
      ) {{
        id
        name
        displayName
        service
        isDisconnected
        isLocked
      }}
    }}
    """

    data = buffer_request(
        channel_query
    )

    channels = (
        data
        .get("data", {})
        .get("channels", [])
    )

    selected = {}

    for channel in channels:
        service = str(
            channel.get(
                "service",
                "",
            )
        ).lower()

        if service not in TARGET_SERVICES:
            continue

        if channel.get(
            "isDisconnected"
        ):
            print(
                f"Skipping disconnected "
                f"{service} channel."
            )
            continue

        if channel.get(
            "isLocked"
        ):
            print(
                f"Skipping locked "
                f"{service} channel."
            )
            continue

        selected[service] = channel

    missing = (
        TARGET_SERVICES
        -
        set(selected.keys())
    )

    if missing:
        raise RuntimeError(
            "Missing Buffer channels: "
            + ", ".join(
                sorted(missing)
            )
        )

    return selected


# ============================================================
# BUFFER CREATE POST
# ============================================================

def graphql_escape(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace(
            "\r\n",
            "\\n",
        )
        .replace(
            "\n",
            "\\n",
        )
        .replace(
            "\r",
            "\\n",
        )
    )


def create_buffer_post(
    service,
    channel_id,
    text,
    image_urls,
):
    asset_entries = []

    for url in image_urls:
        asset_entries.append(
            """
            {
              image: {
                url: "%s"
              }
            }
            """
            % graphql_escape(url)
        )

    assets = ",\n".join(
        asset_entries
    )

    escaped_text = graphql_escape(
        text
    )

    # Facebook requires an explicit post type.
    # Instagram and LinkedIn use the normal post input.
    service_input = ""

    if service == "facebook":
        service_input = """
          type: post
        """

    mutation = f"""
    mutation CreatePost {{
      createPost(
        input: {{
          text: "{escaped_text}"
          channelId: "{graphql_escape(channel_id)}"
          schedulingType: automatic
          mode: shareNow
          {service_input}
          assets: [
            {assets}
          ]
        }}
      ) {{
        ... on PostActionSuccess {{
          post {{
            id
            text
            status
            dueAt
            assets {{
              id
              mimeType
            }}
          }}
        }}

        ... on MutationError {{
          message
        }}
      }}
    }}
    """

    data = buffer_request(
        mutation
    )

    result = (
        data
        .get("data", {})
        .get("createPost", {})
    )

    if result.get("message"):
        raise RuntimeError(
            "Buffer rejected post:\n"
            + str(
                result["message"]
            )
        )

    post = result.get(
        "post"
    )

    if not post:
        raise RuntimeError(
            "Buffer did not return "
            "a created post:\n"
            + json.dumps(
                data,
                indent=2,
            )
        )

    return post


# ============================================================
# PUBLISH
# ============================================================

def publish():
    print("=" * 65)
    print(
        "BUFFER PUBLICATION"
    )
    print("=" * 65)

    post = read_json(
        PENDING_FILE,
        None,
    )

    if not post:
        raise RuntimeError(
            "pending_post.json not found."
        )

    image_urls = post.get(
        "image_urls",
        [],
    )

    if not image_urls:
        raise RuntimeError(
            "No public image URLs found."
        )

    for url in image_urls:
        verify_public_url(
            url,
            attempts=5,
        )

    channels = get_buffer_channels()

    print("\nConnected Buffer channels:")

    for service, channel in channels.items():
        print(
            f"- {service}: "
            f"{channel.get('displayName') or channel.get('name')}"
        )

    caption = post["caption"]

    results = {}

    for service in (
        "facebook",
        "instagram",
        "linkedin",
    ):
        print(
            f"\nPublishing to "
            f"{service.title()}..."
        )

        result = create_buffer_post(
            service,
            channels[service]["id"],
            caption,
            image_urls,
        )

        results[service] = result

        print(
            f"{service.title()} post created: "
            f"{result['id']}"
        )

    post[
        "publication_status"
    ] = "published"

    post[
        "published_at_utc"
    ] = now_utc().isoformat()

    post[
        "buffer_posts"
    ] = {
        service: result["id"]
        for service, result
        in results.items()
    }

    write_json(
        POST_FILE,
        post,
    )

    write_json(
        PENDING_FILE,
        post,
    )

    print(
        "\nAll three Buffer posts "
        "were created successfully."
    )


# ============================================================
# FINALIZE HISTORY
# ============================================================

def finalize():
    print("=" * 65)
    print(
        "FINALIZING CONTENT HISTORY"
    )
    print("=" * 65)

    post = read_json(
        PENDING_FILE,
        None,
    )

    if not post:
        raise RuntimeError(
            "pending_post.json not found."
        )

    if (
        post.get(
            "publication_status"
        )
        != "published"
    ):
        raise RuntimeError(
            "Publication was not successful. "
            "History will not be updated."
        )

    history = load_history()

    existing_ids = set()

    for item in history:
        for post_id in (
            item.get(
                "buffer_posts",
                {}
            ).values()
        ):
            existing_ids.add(
                str(post_id)
            )

    current_ids = set(
        str(post_id)
        for post_id in (
            post.get(
                "buffer_posts",
                {}
            ).values()
        )
    )

    if (
        current_ids
        and current_ids & existing_ids
    ):
        print(
            "This publication already exists "
            "in history. Skipping duplicate."
        )
    else:
        history.append(
            {
                "date": post["date"],
                "generated_at_utc": post[
                    "generated_at_utc"
                ],
                "published_at_utc": post.get(
                    "published_at_utc"
                ),
                "author": post[
                    "author"
                ],
                "theme": post[
                    "theme"
                ],
                "caption": post[
                    "caption"
                ],
                "description": post[
                    "description"
                ],
                "seo_keywords": post[
                    "seo_keywords"
                ],
                "image_count": post[
                    "image_count"
                ],
                "image_files": post[
                    "image_files"
                ],
                "buffer_posts": post.get(
                    "buffer_posts",
                    {},
                ),
            }
        )

    write_json(
        HISTORY_FILE,
        history,
    )

    write_json(
        POST_FILE,
        post,
    )

    if PENDING_FILE.exists():
        PENDING_FILE.unlink()

    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "github-actions[bot]",
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]"
            "@users.noreply.github.com",
        ],
        check=True,
    )

    subprocess.run(
        [
            "git",
            "add",
            "content_history.json",
            "post_data.json",
            "pending_post.json",
        ],
        check=True,
    )

    check = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ]
    )

    if check.returncode != 0:
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                "Save successful daily social media history",
            ],
            check=True,
        )

        subprocess.run(
            [
                "git",
                "push",
                "origin",
                BRANCH,
            ],
            check=True,
        )

    print(
        f"Permanent history contains "
        f"{len(history)} successful posts."
    )


# ============================================================
# MAIN
# ============================================================

def main():
    if len(sys.argv) != 2:
        raise RuntimeError(
            "Use one of:\n"
            "  generate\n"
            "  publish\n"
            "  finalize"
        )

    command = sys.argv[1].lower()

    if command == "generate":
        generate()

    elif command == "publish":
        publish()

    elif command == "finalize":
        finalize()

    else:
        raise RuntimeError(
            f"Unknown command: {command}"
        )


if __name__ == "__main__":
    main()
