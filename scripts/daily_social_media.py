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


# ------------------------------------------------------------
# SETTINGS
# ------------------------------------------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_IMAGE_URL = "https://openrouter.ai/api/v1/images"
BUFFER_URL = "https://api.buffer.com"

# OpenRouter can route through fallback models.
TEXT_MODELS = [
    "openai/gpt-chat-latest",
    "openrouter/free",
]

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

MAX_HISTORY_FOR_PROMPT = 25
MAX_LOCAL_HISTORY = 365

TARGET_SERVICES = {
    "facebook",
    "instagram",
    "linkedin",
}


# ------------------------------------------------------------
# BASIC HELPERS
# ------------------------------------------------------------

def now_utc():
    return datetime.now(timezone.utc)


def today_string():
    return now_utc().strftime("%Y-%m-%d")


def safe_filename(text):
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", text)
    return text.strip("-_").lower()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2,
        )


def read_json(path, default):
    if not path.exists():
        return default

    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def normalize_text(text):
    text = text.lower()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def words(text):
    return set(normalize_text(text).split())


def similarity(a, b):
    a_words = words(a)
    b_words = words(b)

    if not a_words or not b_words:
        return 0.0

    intersection = len(a_words & b_words)
    union = len(a_words | b_words)

    return intersection / union if union else 0.0


def sha256_text(text):
    return hashlib.sha256(
        normalize_text(text).encode("utf-8")
    ).hexdigest()


# ------------------------------------------------------------
# HISTORY
# ------------------------------------------------------------

def load_history():
    data = read_json(HISTORY_FILE, [])

    if not isinstance(data, list):
        return []

    return data


def compact_history(history):
    result = []

    for item in history[-MAX_HISTORY_FOR_PROMPT:]:
        result.append(
            {
                "date": item.get("date", ""),
                "theme": item.get("theme", ""),
                "caption": item.get("caption", "")[:700],
            }
        )

    return result


def history_theme_list(history):
    themes = []

    for item in history:
        theme = str(item.get("theme", "")).strip()

        if theme:
            themes.append(theme)

    return themes[-100:]


# ------------------------------------------------------------
# OPENROUTER TEXT
# ------------------------------------------------------------

def openrouter_chat(messages, temperature=0.9):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": (
            "https://beneficial382-hash.github.io/"
            "social-media-automation/"
        ),
        "X-Title": "Fazl Ullah Azaad Daily Social Media Automation",
    }

    payload = {
        "models": TEXT_MODELS,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 3000,
    }

    response = requests.post(
        OPENROUTER_URL,
        headers=headers,
        json=payload,
        timeout=180,
    )

    if not response.ok:
        raise RuntimeError(
            "OpenRouter text request failed: "
            f"{response.status_code}\n{response.text}"
        )

    data = response.json()

    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(
            "OpenRouter returned an unexpected response:\n"
            + json.dumps(data, indent=2)[:5000]
        )

    if isinstance(content, list):
        parts = []

        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))

        content = "\n".join(parts)

    return str(content).strip()


# ------------------------------------------------------------
# JSON EXTRACTION
# ------------------------------------------------------------

def extract_json(text):
    text = text.strip()

    # Remove markdown code fences.
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

    # Find first JSON object.
    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        candidate = text[start:end + 1]

        try:
            return json.loads(candidate)
        except Exception:
            pass

    raise RuntimeError(
        "The AI did not return valid JSON.\n\n"
        + text[:5000]
    )


# ------------------------------------------------------------
# CONTENT GENERATION
# ------------------------------------------------------------

def generate_content(history):
    previous_posts = compact_history(history)
    previous_themes = history_theme_list(history)

    system_prompt = """
You are the professional personal-brand content strategist and
editor for Fazl Ullah Azaad.

Create ONE original social-media post about real life.

The content must feel:
- intelligent
- mature
- realistic
- meaningful
- practical
- human
- authentic
- naturally motivational
- professionally written

It must NOT sound like generic AI motivational content.

Do not invent achievements, experiences, quotations, statistics,
research findings, events, conversations, or personal stories.

Do not attribute a quotation to a famous person.

Do not write political persuasion.

Do not make exaggerated promises.

Do not use empty phrases such as:
"Believe in yourself and anything is possible"
unless they are transformed into a genuinely original idea.

The central idea must be different from previous posts.

A different wording of the same lesson is NOT considered original.

The post should normally be suitable for Facebook, Instagram,
and LinkedIn at the same time.

Return ONLY valid JSON.
No markdown.
No explanation outside the JSON.

Required JSON structure:

{
  "theme": "short description of the central idea",
  "caption": "the complete social media caption",
  "description": "short description of the post",
  "seo_keywords": ["keyword 1", "keyword 2"],
  "facebook_instagram_hashtags": ["#...", "#..."],
  "linkedin_hashtags": ["#...", "#..."],
  "image_count": 1,
  "image_prompts": [
    "complete image generation prompt"
  ]
}

Rules for image_count:
- Choose exactly 1 or exactly 2.
- Use 2 only when two distinct images genuinely improve the post.
- Otherwise use 1.
- Never choose 0.
- Every image prompt must be different.
- Images must be photorealistic and cinematic.
- Vertical 9:16 composition.
- Professional personal-brand style.
- No text.
- No letters.
- No words.
- No logos.
- No watermark.
- No quotes printed inside the image.
- No artificial-looking typography.

Image prompts should visually communicate the idea of the post,
not literally display the caption.
"""


    user_prompt = f"""
Today's date: {today_string()}

PREVIOUS POST HISTORY:
{json.dumps(previous_posts, ensure_ascii=False, indent=2)}

PREVIOUS THEMES:
{json.dumps(previous_themes, ensure_ascii=False, indent=2)}

IMPORTANT ORIGINALITY REQUIREMENT:

The new post must be substantially different from previous posts
in BOTH:

1. wording
2. central idea / lesson / perspective / angle

Do NOT simply rewrite an old post with different words.

Do NOT reuse an old theme with a new example.

Choose a genuinely different aspect of real life.

Possible areas include, but are not limited to:
- discipline
- time
- patience
- failure
- learning
- communication
- responsibility
- consistency
- self-respect
- decision-making
- relationships
- work
- education
- leadership
- personal growth
- confidence
- boundaries
- money habits
- digital life
- attention
- delayed gratification
- dealing with uncertainty
- adapting to change
- helping others
- character
- practical wisdom

These are examples only. Do not mechanically rotate through them.

Create something genuinely fresh.
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
        temperature=0.95,
    )

    data = extract_json(raw)

    validate_content(data)

    return data


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
                f"Generated content is missing: {key}"
            )

    if not isinstance(data["image_count"], int):
        raise RuntimeError("image_count must be an integer.")

    if data["image_count"] not in (1, 2):
        raise RuntimeError("image_count must be 1 or 2.")

    if not isinstance(data["image_prompts"], list):
        raise RuntimeError("image_prompts must be a list.")

    if len(data["image_prompts"]) != data["image_count"]:
        raise RuntimeError(
            "Number of image prompts does not match image_count."
        )

    for key in [
        "caption",
        "description",
        "theme",
    ]:
        if not str(data[key]).strip():
            raise RuntimeError(
                f"{key} cannot be empty."
            )


# ------------------------------------------------------------
# LOCAL ORIGINALITY CHECK
# ------------------------------------------------------------

def check_local_originality(candidate, history):
    candidate_text = (
        candidate.get("theme", "")
        + " "
        + candidate.get("caption", "")
    )

    candidate_hash = sha256_text(candidate_text)

    for item in history:
        old_text = (
            item.get("theme", "")
            + " "
            + item.get("caption", "")
        )

        if sha256_text(old_text) == candidate_hash:
            return False, "Exact duplicate detected."

    # Reject very similar wording against recent posts.
    recent = history[-60:]

    for item in recent:
        old_text = (
            item.get("theme", "")
            + " "
            + item.get("caption", "")
        )

        score = similarity(candidate_text, old_text)

        if score >= 0.72:
            return (
                False,
                "Candidate is too textually similar "
                f"to a previous post ({score:.2f}).",
            )

    return True, "Local originality check passed."


# ------------------------------------------------------------
# AI ORIGINALITY AUDIT
# ------------------------------------------------------------

def ai_originality_audit(candidate, history):
    previous = compact_history(history)

    prompt = f"""
You are an extremely strict originality editor.

Evaluate whether this proposed social-media post has a genuinely
different central idea from the previous posts.

PROPOSED POST:
{json.dumps(candidate, ensure_ascii=False, indent=2)}

PREVIOUS POSTS:
{json.dumps(previous, ensure_ascii=False, indent=2)}

A post is NOT original if it:
- repeats the same lesson
- merely changes wording
- changes the example but keeps the same central message
- uses the same perspective with superficial changes

Return ONLY JSON:

{{
  "original": true,
  "reason": "short explanation"
}}
"""

    raw = openrouter_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are a strict editorial originality auditor. "
                    "Return valid JSON only."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        temperature=0.1,
    )

    result = extract_json(raw)

    original = result.get("original")

    if isinstance(original, str):
        original = original.lower() == "true"

    return bool(original), str(
        result.get("reason", "")
    )


# ------------------------------------------------------------
# IMAGE GENERATION
# ------------------------------------------------------------

def generate_image(prompt, output_path):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "aspect_ratio": "9:16",
        "resolution": "1K",
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
            "OpenRouter image request failed: "
            f"{response.status_code}\n{response.text}"
        )

    data = response.json()

    try:
        image_data = data["data"][0]["b64_json"]
    except Exception:
        raise RuntimeError(
            "OpenRouter did not return b64_json:\n"
            + json.dumps(data, indent=2)[:5000]
        )

    raw_bytes = base64.b64decode(image_data)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_bytes(raw_bytes)

    if output_path.stat().st_size < 1000:
        raise RuntimeError(
            f"Generated image appears invalid: {output_path}"
        )

    print(
        f"Generated image: {output_path} "
        f"({output_path.stat().st_size:,} bytes)"
    )


# ------------------------------------------------------------
# GITHUB PUBLIC URL
# ------------------------------------------------------------

def github_raw_url(relative_path):
    relative = str(relative_path).replace("\\", "/")

    return (
        f"https://raw.githubusercontent.com/"
        f"{REPO_OWNER}/{REPO_NAME}/{BRANCH}/{relative}"
    )


def wait_for_public_url(url, attempts=12):
    print(f"Waiting for public image URL:\n{url}")

    for attempt in range(1, attempts + 1):
        try:
            response = requests.head(
                url,
                timeout=20,
                allow_redirects=True,
            )

            if response.status_code == 200:
                print("Public image URL is available.")
                return

        except requests.RequestException:
            pass

        print(
            f"Image not available yet "
            f"(attempt {attempt}/{attempts})"
        )

        time.sleep(5)

    raise RuntimeError(
        "Generated image was committed, but its public GitHub URL "
        "did not become available in time."
    )


# ------------------------------------------------------------
# GITHUB COMMIT
# ------------------------------------------------------------

def git_commit_and_push(message):
    print("Saving generated files to GitHub...")

    commands = [
        ["git", "config", "user.name", "github-actions[bot]"],
        [
            "git",
            "config",
            "user.email",
            "41898282+github-actions[bot]@users.noreply.github.com",
        ],
        ["git", "add", "site", "post_data.json", "pending_post.json"],
        [
            "git",
            "status",
            "--short",
        ],
    ]

    for command in commands:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Git command failed:\n"
                f"{' '.join(command)}\n"
                f"{result.stderr}"
            )

        if result.stdout.strip():
            print(result.stdout)

    check = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ]
    )

    if check.returncode == 0:
        print("No Git changes to commit.")
        return

    result = subprocess.run(
        [
            "git",
            "commit",
            "-m",
            message,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git commit failed:\n" + result.stderr
        )

    result = subprocess.run(
        ["git", "push", "origin", BRANCH],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Git push failed:\n" + result.stderr
        )

    print("GitHub files successfully committed and pushed.")


# ------------------------------------------------------------
# BUFFER API
# ------------------------------------------------------------

def buffer_request(query):
    response = requests.post(
        BUFFER_URL,
        headers={
            "Authorization": f"Bearer {BUFFER_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "query": query,
        },
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            "Buffer API HTTP error: "
            f"{response.status_code}\n{response.text}"
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
    query = """
    query GetOrganizationsAndChannels {
      account {
        organizations {
          id
          name
        }
      }
    }
    """

    data = buffer_request(query)

    organizations = (
        data.get("data", {})
        .get("account", {})
        .get("organizations", [])
    )

    if not organizations:
        raise RuntimeError(
            "No Buffer organizations were found."
        )

    organization_id = organizations[0]["id"]

    channel_query = f"""
    query GetChannels {{
      channels(input: {{
        organizationId: "{organization_id}"
      }}) {{
        id
        name
        displayName
        service
        isDisconnected
        isLocked
      }}
    }}
    """

    data = buffer_request(channel_query)

    channels = (
        data.get("data", {})
        .get("channels", [])
    )

    selected = {}

    for channel in channels:
        service = str(
            channel.get("service", "")
        ).lower()

        if service in TARGET_SERVICES:
            if channel.get("isDisconnected"):
                print(
                    f"Skipping disconnected channel: "
                    f"{service}"
                )
                continue

            if channel.get("isLocked"):
                print(
                    f"Skipping locked channel: "
                    f"{service}"
                )
                continue

            selected[service] = channel

    missing = TARGET_SERVICES - set(selected)

    if missing:
        raise RuntimeError(
            "These Buffer channels were not found: "
            + ", ".join(sorted(missing))
        )

    return selected


def create_buffer_post(
    channel_id,
    text,
    image_urls,
):
    assets = ""

    for url in image_urls:
        escaped_url = (
            url.replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        assets += f"""
        {{
          image: {{
            url: "{escaped_url}"
          }}
        }}
        """

    escaped_text = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )

    query = f"""
    mutation CreatePost {{
      createPost(
        input: {{
          text: "{escaped_text}"
          channelId: "{channel_id}"
          schedulingType: automatic
          mode: shareNow
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
          }}
        }}
        ... on MutationError {{
          message
        }}
      }}
    }}
    """

    data = buffer_request(query)

    result = (
        data.get("data", {})
        .get("createPost", {})
    )

    if result.get("message"):
        raise RuntimeError(
            "Buffer rejected the post: "
            + str(result["message"])
        )

    post = result.get("post")

    if not post:
        raise RuntimeError(
            "Buffer did not return a created post:\n"
            + json.dumps(data, indent=2)
        )

    return post


# ------------------------------------------------------------
# GENERATE
# ------------------------------------------------------------

def generate():
    print("=" * 60)
    print("FAZL ULLAH AZAAD DAILY CONTENT GENERATION")
    print("=" * 60)

    history = load_history()

    print(
        f"Previous successful posts in history: "
        f"{len(history)}"
    )

    max_attempts = 5
    candidate = None

    for attempt in range(1, max_attempts + 1):
        print(
            f"\nGenerating candidate "
            f"{attempt}/{max_attempts}..."
        )

        candidate = generate_content(history)

        ok, reason = check_local_originality(
            candidate,
            history,
        )

        print(reason)

        if not ok:
            continue

        audit_ok, audit_reason = ai_originality_audit(
            candidate,
            history,
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
            "Could not create a sufficiently original post "
            "after multiple attempts."
        )

    print("\nSelected theme:")
    print(candidate["theme"])

    print("\nCaption:")
    print(candidate["caption"])

    image_count = candidate["image_count"]

    day = today_string()

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
            f"{day}-"
            f"{safe_filename(candidate['theme'])[:50]}-"
            f"{index}.jpg"
        )

        output_path = MEDIA_DIR / filename

        print(
            f"\nGenerating image {index}/{image_count}..."
        )

        generate_image(
            prompt,
            output_path,
        )

        relative_path = output_path.relative_to(ROOT)

        public_url = github_raw_url(
            relative_path
        )

        image_files.append(
            str(relative_path).replace("\\", "/")
        )

        image_urls.append(public_url)

    post_data = {
        "date": day,
        "generated_at_utc": now_utc().isoformat(),
        "author": "Fazl Ullah Azaad",
        "theme": candidate["theme"],
        "caption": candidate["caption"],
        "description": candidate["description"],
        "seo_keywords": candidate["seo_keywords"],
        "facebook_instagram_hashtags": candidate[
            "facebook_instagram_hashtags"
        ],
        "linkedin_hashtags": candidate[
            "linkedin_hashtags"
        ],
        "image_count": image_count,
        "image_prompts": candidate["image_prompts"],
        "image_files": image_files,
        "image_urls": image_urls,
        "publication_status": "pending",
    }

    write_json(
        POST_FILE,
        post_data,
    )

    write_json(
        PENDING_FILE,
        post_data,
    )

    # Create a simple public archive page.
    create_site_page(post_data)

    # Commit images and generated content BEFORE Buffer.
    # This makes the image URLs publicly accessible.
    git_commit_and_push(
        "Generate daily social media content"
    )

    # Verify that every image URL is public.
    for url in image_urls:
        wait_for_public_url(url)

    print("\nGeneration completed successfully.")
    print("Images are now publicly accessible.")
    print("Ready for Buffer publication.")


# ------------------------------------------------------------
# PUBLIC GITHUB PAGES SITE
# ------------------------------------------------------------

def html_escape(text):
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def create_site_page(post):
    SITE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    image_html = ""

    for url in post["image_urls"]:
        image_html += f"""
        <img
          src="{html_escape(url)}"
          alt="Daily visual"
          loading="lazy"
        >
        """

    hashtags = (
        post["facebook_instagram_hashtags"]
        + post["linkedin_hashtags"]
    )

    hashtag_text = " ".join(
        dict.fromkeys(hashtags)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1.0">

<title>
Fazl Ullah Azaad - Daily Social Media
</title>

<meta name="description"
      content="{html_escape(post['description'])}">

<style>
body {{
    font-family: Arial, sans-serif;
    max-width: 900px;
    margin: 0 auto;
    padding: 30px 18px;
    line-height: 1.7;
    background: #ffffff;
    color: #111111;
}}

h1 {{
    line-height: 1.2;
}}

.card {{
    border: 1px solid #dddddd;
    padding: 24px;
    border-radius: 12px;
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
    display: block;
}}

.caption {{
    white-space: pre-wrap;
}}

.small {{
    color: #555555;
    font-size: 14px;
}}
</style>
</head>

<body>

<div class="card">

<h1>
Fazl Ullah Azaad
</h1>

<p class="small">
Daily personal-brand social media post
</p>

<h2>
{html_escape(post["theme"])}
</h2>

<div class="caption">
{html_escape(post["caption"])}
</div>

<div class="images">
{image_html}
</div>

<p>
<strong>SEO Keywords:</strong><br>
{html_escape(", ".join(post["seo_keywords"]))}
</p>

<p>
<strong>Hashtags:</strong><br>
{html_escape(hashtag_text)}
</p>

<p class="small">
Generated: {html_escape(post["generated_at_utc"])}
</p>

</div>

</body>
</html>
"""

    write_json(
        SITE_DIR / "post.json",
        post,
    )

    with (SITE_DIR / "index.html").open(
        "w",
        encoding="utf-8",
    ) as f:
        f.write(html)


# ------------------------------------------------------------
# PUBLISH
# ------------------------------------------------------------

def publish():
    print("=" * 60)
    print("BUFFER PUBLICATION")
    print("=" * 60)

    post = read_json(
        PENDING_FILE,
        None,
    )

    if not post:
        raise RuntimeError(
            "pending_post.json was not found."
        )

    image_urls = post.get(
        "image_urls",
        [],
    )

    if not image_urls:
        raise RuntimeError(
            "No image URLs found."
        )

    channels = get_buffer_channels()

    print("\nBuffer channels found:")

    for service, channel in channels.items():
        print(
            f"- {service}: "
            f"{channel.get('displayName') or channel.get('name')}"
        )

    caption = post["caption"]

    successful = {}

    # Facebook
    print("\nPublishing to Facebook...")

    successful["facebook"] = create_buffer_post(
        channels["facebook"]["id"],
        caption,
        image_urls,
    )

    print(
        "Facebook post created: "
        + successful["facebook"]["id"]
    )

    # Instagram
    print("\nPublishing to Instagram...")

    successful["instagram"] = create_buffer_post(
        channels["instagram"]["id"],
        caption,
        image_urls,
    )

    print(
        "Instagram post created: "
        + successful["instagram"]["id"]
    )

    # LinkedIn
    print("\nPublishing to LinkedIn...")

    successful["linkedin"] = create_buffer_post(
        channels["linkedin"]["id"],
        caption,
        image_urls,
    )

    print(
        "LinkedIn post created: "
        + successful["linkedin"]["id"]
    )

    post["publication_status"] = "published"

    post["buffer_posts"] = {
        service: result.get("id")
        for service, result in successful.items()
    }

    post["published_at_utc"] = (
        now_utc().isoformat()
    )

    write_json(
        POST_FILE,
        post,
    )

    write_json(
        PENDING_FILE,
        post,
    )

    print("\nAll three Buffer publications succeeded.")


# ------------------------------------------------------------
# FINALIZE HISTORY
# ------------------------------------------------------------

def finalize():
    print("=" * 60)
    print("FINALIZING CONTENT HISTORY")
    print("=" * 60)

    post = read_json(
        PENDING_FILE,
        None,
    )

    if not post:
        raise RuntimeError(
            "pending_post.json is missing."
        )

    if post.get("publication_status") != "published":
        raise RuntimeError(
            "Post has not been successfully published. "
            "History will NOT be updated."
        )

    history = load_history()

    history_entry = {
        "date": post["date"],
        "generated_at_utc": post[
            "generated_at_utc"
        ],
        "published_at_utc": post.get(
            "published_at_utc"
        ),
        "theme": post["theme"],
        "caption": post["caption"],
        "description": post["description"],
        "seo_keywords": post["seo_keywords"],
        "image_count": post["image_count"],
        "image_files": post["image_files"],
        "buffer_posts": post.get(
            "buffer_posts",
            {},
        ),
    }

    history.append(history_entry)

    # Keep the full history.
    write_json(
        HISTORY_FILE,
        history,
    )

    # Also make the public post record final.
    write_json(
        POST_FILE,
        post,
    )

    # Remove pending state.
    if PENDING_FILE.exists():
        PENDING_FILE.unlink()

    # Save history.
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

    commit_check = subprocess.run(
        [
            "git",
            "diff",
            "--cached",
            "--quiet",
        ]
    )

    if commit_check.returncode != 0:
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
                "41898282+github-actions[bot]@users.noreply.github.com",
            ],
            check=True,
        )

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
        f"History now contains {len(history)} successful posts."
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        raise RuntimeError(
            "Usage:\n"
            "python scripts/daily_social_media.py generate\n"
            "python scripts/daily_social_media.py publish\n"
            "python scripts/daily_social_media.py finalize"
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
