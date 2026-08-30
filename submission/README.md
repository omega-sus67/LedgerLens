# Submission artefacts — Accenture Innovation Challenge 2026, Round 2

Generated files. **The sources are the authority**; these are rendered from them, so
edit the markdown and rebuild — never edit a PDF or the deck by hand.

| File | Source | Form field |
|---|---|---|
| `LedgerLens_README.pdf` | [`../README.md`](../README.md) | "Please submit a README document" |
| `LedgerLens_Business_Proposal.pdf` | [`../docs/business_proposal.md`](../docs/business_proposal.md) | "Detailed Business Proposal in PDF" |
| `LedgerLens_Business_Proposal.pptx` | the same, reworked onto the Round 1 deck | "Detailed Business Proposal in PPT" |

**Public GitHub link:** https://github.com/omega-sus67/LedgerLens

The prototype video is recorded by hand — see [`../docs/demo_script.md`](../docs/demo_script.md).

## Rebuilding

The PDFs are `markdown` -> styled HTML -> headless Chrome. The deck is
[`../docs/taskflow/build_deck.py`](../docs/taskflow/build_deck.py), which opens the Round 1
file so the Accenture master, theme and 16:9 geometry carry over, keeps slides 1-4 and the
closing two, and inserts the Round 2 content between them. It also recompresses the
template's 9000px cover art, which alone accounted for 12 MB of an 18.5 MB deck.

```bash
uv run --with python-pptx --with pillow python docs/taskflow/build_deck.py
```

## Two placeholders the build cannot fill

`build_deck.py` substitutes these when present; otherwise the Round 1 placeholder text
survives and the script says so on stdout.

| File | Fills |
|---|---|
| `submission/.team_name` | slide 2's `[ADD TEAM NAME]` |
| `submission/.video_url` | slide 17's `[ADD VIDEO LINK HERE]` |

**Slide 2 also carries stock template headshots for both team members.** They are the
Round 1 file's placeholder images, not photographs of anyone on this team - replace them
before submitting, since the slide itself states that all fields are mandatory.
