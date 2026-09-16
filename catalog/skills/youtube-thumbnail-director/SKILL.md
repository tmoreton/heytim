---
name: youtube-thumbnail-director
description: Turn a video's promise into a polished, mobile-readable YouTube thumbnail with deliberate art direction and requested text overlays.
---

# YouTube Thumbnail Director

Use this skill for thumbnail concepts or generated YouTube thumbnail images.

Start from the video's real promise, target viewer, emotional hook, and one focal idea. A thumbnail should communicate one visual story at phone size, not summarize the whole video.

Before calling the image tool, silently rewrite the user's idea into a production-ready visual brief. Keep the user's subject and requested style, then add only the missing art direction:

1. Describe one dominant visual metaphor or focal scene rather than a collection of related objects.
2. Specify intentional asymmetry, large readable shapes, foreground/midground depth, and a clear focal hierarchy.
3. Match the palette, lighting, texture, and visual language to the channel, subject, and target viewer. Preserve crisp focal contrast and phone-size legibility; use saturated complementary colors, cinematic rim lighting, or editorial tech polish only when they fit the concept instead of making them the default.
4. For comparisons, use visual tension and contrasting warm/cool color when helpful, but do not default every concept to a literal diagonal split.
5. Describe how the headline, supplied portrait, and supplied logos belong inside the composition. Prefer a natural presenter cutout or photographed subject over a circular avatar. Integrate transparent logos without app tiles, white cards, or thick borders unless the concept specifically calls for one.
6. Keep all essential elements inside a generous safe area so the generated result can be center-cropped to exact 1280x720 output.

Avoid genre-incongruent filler, muddy darkness, tiny decorative details, and stock visual shorthand. In technology concepts, specifically avoid defaulting to desks full of monitors, rows of glowing spheres, fake dashboards, or unrelated futuristic scenery unless the user asks for them.

Use `create_youtube_thumbnail` to render thumbnails. It sends the entire composition, requested copy, and selected recent images to the configured OpenRouter image model in one request. The tool returns a 1280x720 PNG. Use the numbered recent image references as the source of truth. Use `generate_image` only when the user wants standalone artwork rather than a thumbnail.

Keep the main hook to roughly two to five words and use an optional short secondary line only when it adds new information. Do not repeat the full video title or say the same thing twice. Preserve the requested spelling in the visual brief, but do not assume the image model rendered it correctly.

When generating multiple variants, change the visual story, emotional hook, subject scale, and layout—not merely the background color. Do not force every variant into the same portrait corner, logo corner, split-screen, or caption-pill template. Before retrying a weak result, reassess the concept and remove any failed motif such as fake UI, generic monitors, spheres, oversized copy, boxed logos, or redundant captions; do not preserve it just because it appeared in an earlier image.

If an exact brand mark is needed, ask for or reuse an official uploaded asset. Do not redraw a trademarked logo from memory.

After the image tool returns, inspect the PNG at full size and at a phone-size preview. Check every requested word, missing or extra characters, and any unexpected visible text; the tool's success message alone is not proof that the copy is correct. If the text is wrong, make at most one retry with the same requested words, simpler typography, or a less crowded composition. Do not shorten or rewrite user-supplied copy without permission. If the retry still fails, or the current environment cannot show the result for inspection, label the image as a draft and state the specific defect or verification limit. Call it finished only after the visual check passes. Never claim that an image exists before the tool returns it.
