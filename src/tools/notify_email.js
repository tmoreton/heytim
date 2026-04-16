// Send an email notification with a markdown body. Renders to HTML for the
// HTML alternative and keeps the original markdown as the plain-text part.
// Requires SMTP_HOST/USER/PASS env vars (see src/smtp.js for the full list).
// Confirmation is required before sending — supports "always" for the session.

import { confirm } from "../permissions.js";
import { sendMail, smtpConfig } from "../smtp.js";
import { markdownToHtml, wrapEmailHtml } from "../markdown.js";

const truncate = (s, n) => (s.length <= n ? s : s.slice(0, n) + "…");

export const notifyEmail = {
  schema: {
    type: "function",
    function: {
      name: "notify_email",
      description:
        "Send an email notification with a markdown-formatted body (rendered to HTML). Use this to notify the user when a long-running task completes or to share a written report. Recipient defaults to SMTP_TO env var if set.",
      parameters: {
        type: "object",
        properties: {
          to: {
            oneOf: [
              { type: "string" },
              { type: "array", items: { type: "string" } },
            ],
            description:
              "Recipient address(es). Defaults to SMTP_TO env var if not provided.",
          },
          cc: {
            type: "array",
            items: { type: "string" },
            description: "Optional CC recipients.",
          },
          subject: { type: "string" },
          body: {
            type: "string",
            description: "Email body in markdown. Rendered to HTML for sending.",
          },
        },
        required: ["subject", "body"],
      },
    },
  },
  run: async ({ to, cc, subject, body }) => {
    const recipients = to || process.env.SMTP_TO;
    if (!recipients) {
      return "ERROR: no recipient. Pass `to` or set SMTP_TO env var.";
    }

    try {
      // Validate config early so confirm() doesn't ask for permission to run
      // a send that would have failed anyway.
      smtpConfig();
    } catch (e) {
      return `ERROR: ${e.message}`;
    }

    const toList = Array.isArray(recipients) ? recipients : [recipients];
    const preview = `to: ${toList.join(", ")}\nsubject: ${subject}\n\n${truncate(body, 400)}`;
    const ok = await confirm("notify_email", { to: toList, subject }, preview);
    if (!ok) return "User denied the email send.";

    try {
      const html = wrapEmailHtml(markdownToHtml(body), subject);
      await sendMail({ to: toList, cc, subject, text: body, html });
      return `sent to ${toList.join(", ")}`;
    } catch (e) {
      return `ERROR: ${e.message}`;
    }
  },
};
