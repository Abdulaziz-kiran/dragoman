# Translator and reviewer guide

This guide accompanies every translation and review request. Editing it changes the guide hash in `record.json`.

## Audience

Viewers who want professional, natural subtitles in the target language.

## Quality

1. **Meaning first.** Identify who speaks, to whom, and with what intent. Preserve negation, questions, commands, requests, tense, certainty, and possession/direction. Never add or remove information, emotion or jokes.
2. **Natural target language.** Rebuild sentences in the target language; do not carry over source syntax. Omit unnecessary pronouns only when meaning and emphasis survive.
3. **Professional language.** Neither stiff literalism nor invented slang. Use clear, natural language, literary where appropriate. Preserve actual vulgarity and slang without softening it.
4. **Voice and social distance.** Follow character notes and directional register decisions. Do not change distance unless the source does.
5. **Address and honorifics.** Keep source honorifics only if common for the target audience; never invent them. Translate titles and ranks naturally in the target language. Apply any target-language addendum.
6. **Terminology.** Use locked series terminology consistently.
7. **No spoiler leakage.** Later knowledge in the series guide must not enter the current line.
8. **Decision order.** For each line: (a) source meaning and speaker/listener direction; (b) speech act, negation, tense, cause/effect and certainty; (c) relationship tone, social distance and voice; (d) natural target language; (e) shortening for reading time. Reject a later choice if it damages an earlier requirement.
9. **Do not invent ambiguity resolutions.** Do not assume gender, number, addressee or pronoun referents without evidence. Recheck possession and direction. Consult neighboring lines first; if still unresolved, preserve ambiguity rather than guessing fluently.
10. **Context does not override source.** Series notes, episode context and character voice resolve ambiguity, maintain register and choose among equivalent phrasings. They never justify changing explicit source meaning.
11. **Shortening must preserve meaning.** Prefer economical equivalent phrasing. Do not drop negation, questions, possibility, significant repetition, humor or emotional weight to save space.
12. **Pivot translation warning.** Source subtitles may already be translated from another language. Do not reconstruct an imagined original from memory and use it to override the supplied source.

## Error counterexamples

| Error type | What to avoid | Correct direction |
|---|---|---|
| Reversed action | Translating an instruction as its opposite | Preserve the action and speech act |
| Invented slang | Adding playful familiarity absent from the source | Match the source register |
| Omitted clause | Dropping the second part of a request | Account for every meaning unit |
| Mechanical title | Combining incompatible titles or copying source order | Use natural target address forms |
| Reversed possession | Changing the listener's relative into the speaker's relative | Verify possession and direction |
| Script corruption | Transliteration or replacement of text meant to remain untouched | Preserve retained lines exactly |

## Format

- The script wraps lines. Do not add `\N`; existing source breaks may remain. Avoid needless length without deleting meaning.
- Markers such as `⟦1⟧`, `⟦2⟧` locate formatting tags. Preserve their count and order exactly; their positions within the sentence may move.
- Signs and screen text (`kind: sign`) should be concise and have no added line breaks. Keep untranslatable logos, brands, proper names and mathematical formulas unchanged.
- Songs (`kind: song`) should be fluent and poetic while preserving meaning. Only translate supplied units; script/style exclusions are handled by the program according to the language pair.
- If a line is already in the target language or contains nothing to translate (a name or interjection), retain it or use its natural equivalent. Never return an empty line.

## Reviewer checklist

First divide the source into clauses and verify that every meaning unit has a translation. Do not start by admiring fluency.

- Check each item in lists of three or more.
- Check certainty, modality, tense, negation and words expressing continuing action or uncertainty.
- Verify that no clause silently disappeared from a multi-clause line.
- For idiomatic or strongly localized text, check for added or narrowed meaning, relationship interpretation or tone.
- Check locked terms and directional register decisions, then naturalness, address, terminology and voice.

Return a correction only for a real error. Give the complete replacement line and a one-sentence reason. Taste and synonym preferences are not corrections. Return an empty list if there are no errors.

## No tools

This is a language task. Do not read files, run commands, browse, or use any tool. Return only the requested JSON.
