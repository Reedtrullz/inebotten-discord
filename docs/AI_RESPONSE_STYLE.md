# AI response style

Ine uses natural Bokmål with a calm, friendly tone. Replies should answer the
question directly and be as short as the task allows. A greeting can be:

> Hei. Hva kan jeg hjelpe deg med?

Avoid forced filler words, exaggerated praise, unsolicited introductions,
feature menus and repeated exclamation marks. Use plain text by default,
especially without yellow faces and hand gestures. An explicit request for an
emoji can override that default. Functional calendar, warning and status icons
remain available; generated replies and user text are not globally filtered.

The connector defaults (`ai/system_prompt*.txt`), personalized prompt and local
chat templates share this direction. LM Studio's simplified prompt branches
also receive it. Calendar action proposals still require their existing
confirmation flow. Greetings and general questions should not propose actions.

## Release acceptance

Prompt compliance does not establish Norwegian language quality. Test both a
short greeting and a substantive question through the actual connector with the
personalized prompt used by `MessageMonitor`, then obtain human Discord
acceptance. Do not replace a failed model response with a fixed greeting and
call the model accepted.

The 6 October human canary rejected `liquid/lfm-2.5-2.6b:free`: the response was
exuberant and ungrammatical. After the prompt repair, its greeting improved but
an explanation still contained substantial Norwegian errors. It remains
unsuitable for promotion on that evidence. Choose a currently available,
verified free provider route and repeat acceptance before production activation.

The same trial exposed a second responder: the VPS `inebotten-bot` container
used the same selfbot identity and its older code produced the misleading empty
DM calendar reply alongside the candidate's correct refusal. It was stopped
cleanly with its mounted data preserved and restart policy set to
`unless-stopped`. Keep exactly one responding service for acceptance and
production. Restarting that old container would reintroduce the duplicate.
