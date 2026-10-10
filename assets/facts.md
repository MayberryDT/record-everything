---
facts: 1
name: my-app
environment: production
source:
  kind: http
  list: https://my-app.example/api/facts/v1/archive?prefix=raw/v1/
  get: https://my-app.example/api/facts/v1/archive/{key}
  token_env: MY_APP_FACTS_TOKEN
  token_file: ~/.config/my-app/facts-token
# The defaults match the recommended envelope (kind, t, session, build, actor, who). Map other names here.
# fields:
#   session: round
admin_kinds: [admin]
bulky: [snapshot, window]
kinds:
  session: a player joined or left
  snapshot: once a second with a human connected; world state and one row per actor
  window: inputs and positions around a fight
  admin: an admin command; its session is admin-touched
views: {}
measures: {}
checks: {}
eras: []
---
# my-app facts

Read with `facts` (`facts guide` for the handbook). Write here what a reader needs that the data cannot say: what a
session is, sampling, recorder bugs with their dates, retired kinds.
