# Agent runtime map

```text
request.py                 Validate requests and load attachments
configuration.py           Build bot and group instructions
capabilities.py            Resolve tools, skills, and persistent sessions
memory.py                  Recall and record AgentCore memory
artifacts.py               Create and upload generated files
artifact_content.py        Parse the supported Markdown subset
document_renderers.py      Render PDF and Word files
spreadsheet_renderer.py    Render Excel files
presentation_renderer.py   Render PowerPoint files
artifact_renderers.py      Select the renderer by file extension
telemetry.py               Redact sensitive trace content
```

`main.py` is the transport entrypoint. Runtime behavior belongs in this package so request transport,
agent configuration, and output formats remain independently testable.
