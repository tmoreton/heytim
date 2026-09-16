---
name: meme-maker
description: Create a finished meme from a stored popular template or an image attached by the user.
---

# Meme Lord

Create a finished captioned meme from the private stored template library or an image in the user's latest message.

1. Identify the intended joke, audience, and tone from the request. If the user supplied the wording, preserve its meaning and tighten it only when asked.
2. When the user names a known meme format or does not attach an image, call `search_meme_templates`. Choose the closest stored template and preserve the caption order returned by the search.
3. For a stored template, call `compose_meme` with its `template_id` and an ordered `texts` list. The compositor uses that template's own text regions, alignment, colors, and rotation.
4. For an attached image, use it as the source of truth. Choose `classic` for top-and-bottom text, `top_only` or `bottom_only` for one overlaid caption, and `caption_bar` for black text in a white header above the image. Provide the correct one-based attachment number when more than one image is attached.
5. Keep captions short enough to read at phone size. Prefer one idea per text region and avoid unnecessary punctuation.
6. Do not redraw, replace, or claim broader edits to a template. Original image generation belongs to the separate Image generator tool.
7. After `compose_meme` succeeds, state that the finished PNG is available. Never claim success from a draft caption alone.

If no suitable stored template exists, ask the user to attach the image they want. Do not fetch an arbitrary copy of a meme image from the web.
