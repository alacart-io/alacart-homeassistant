# Alacart for Home Assistant

The Alacart integration shows each of your Alacart shopping lists as a to-do list in Home
Assistant. In Home Assistant you can add items to a list, rename them, check them off and delete
them, by voice through Assist or from an automation. The changes reach the Alacart apps the next
time they sync.

The integration is a custom integration, which you install through HACS, the Home Assistant
Community Store. Its code uses the [`alacart`](https://github.com/alacart-io/alacart-python)
Python library.

## Requirements

- An Alacart account with premium. Home Assistant can link only an account with premium.
- Home Assistant 2026.10 or later.
- HACS, installed as its own documentation describes.

## Installing

The integration is in testing, so HACS installs it from this repository as a custom
repository:

1. In HACS, open the menu in the top right corner and choose *Custom repositories*.
2. Enter `https://github.com/alacart-io/alacart-homeassistant`, choose the type *Integration*, and
   click *Add*.
3. Open *Alacart* in HACS, download it, and restart Home Assistant. Until the integration has a
   full release, HACS installs the newest code on `main`.
4. Turn on pre-releases, so HACS installs released versions. Go to *Settings*, *Devices &
   services*, *Entities*, and open *Alacart Pre-release*. HACS adds the switch disabled, so turn
   on *Enabled* in its settings, and wait about 30 seconds. Then turn the switch on.
5. HACS now offers the newest pre-release under *Settings*, *Updates*. Install it, and restart
   Home Assistant.

After the first full release, you can turn the *Alacart Pre-release* switch off. HACS then offers
only full releases.

## Linking your account

1. Go to *Settings*, *Devices & services*, click *Add integration*, and choose *Alacart*.
2. Sign in to Alacart in the window that opens.
3. Allow Home Assistant to read and change your lists on the consent page.

The sign-in passes through `my.home-assistant.io` on its way back to your Home Assistant, so the
integration turns on Home Assistant's `my` integration. Each shopping list then appears as a to-do
list, named after the list. You can link several Alacart accounts, one at a time.

## How the lists behave

- Home Assistant reads the items on your lists every 5 minutes, and right after each change it
  makes. An item that you add, change or check off in an Alacart app shows up in Home Assistant
  within 5 minutes.
- Home Assistant reads the lists themselves about once an hour. A new, renamed or deleted list
  shows up within about an hour. A new list that gets an item shows up within 5 minutes.
- A list's state is the number of items you have not checked off.
- A checked item shows as completed until Alacart drops it from the list, 180 minutes after the
  check.
- A permanent item stays on its list after shopping. You make an item permanent in the Alacart
  app. Checking it off records the purchase, and the item stays unchecked.
- Items show newest first.

## When something goes wrong

- **Home Assistant asks you to sign in again.** Alacart no longer accepts the sign-in, for example
  because you removed Home Assistant from your connected apps. Follow the notice under *Settings*,
  *Devices & services*.
- **The lists are unavailable.** Home Assistant cannot reach Alacart, or the account no longer has
  premium. The log under *Settings*, *System*, *Logs* says which. The lists come back on their own
  once the cause is gone.
- **Adding an item fails because the list is full.** Remove some items in Alacart, and try again.

To unlink Home Assistant, delete the Alacart integration entry. To also revoke its access, remove
Home Assistant from the connected apps on your Alacart profile page.

Report a problem with the integration on the
[issue tracker](https://github.com/alacart-io/alacart-homeassistant/issues).

## Testing against Alacart's beta

Alacart's beta runs Alacart's public API with test data, for testers and for developers of the
integration.
Most users never need it. To sign in to beta, add these lines to `configuration.yaml` and restart
Home Assistant:

```yaml
alacart:
  server: beta
```

New entries then sign in to beta, and their titles end in `(beta)`. Entries you linked before keep
their server. A beta account needs beta premium, which Alacart gives to the testers it invites.

To move back to production, delete the beta entry, remove the two lines, restart Home Assistant,
and link your account again.

## Signing in with your own developer app

Home Assistant signs in with a client id that Alacart made for it. A developer can sign in with
their own app's client id instead, through Home Assistant's application credentials:

1. Register an app on Alacart's developer page. Add `https://my.home-assistant.io/redirect/oauth`
   as its redirect URI.
2. In Home Assistant, go to *Settings*, *Devices & services*, open the menu, and choose
   *Application credentials*. Add the app's client id. If the developer page gave the app a
   client secret, add the secret too.
3. Add the Alacart integration, and choose your credentials when Home Assistant asks how to sign
   in.

Application credentials sign in to the server that `configuration.yaml` picks. A client id from
beta's developer page works only with `server: beta`.

## Developing

The tests use `pytest-homeassistant-custom-component`, which needs Python 3.14. They run offline,
with no Alacart account. Install the `alacart` version that `manifest.json` names:

```sh
pip install -r requirements_test.txt alacart==0.1.0
ruff format --check .
ruff check .
mypy
pytest
```

GitHub Actions runs these checks on every push to `main` and on pull requests. It also runs
Hassfest, Home Assistant's own check of an integration's files, and the HACS checks.

## Releasing

1. Set the new version in `custom_components/alacart/manifest.json`, and merge the change to
   `main`.
2. Create a GitHub release whose tag is the version with a `v` in front, such as `v0.1.0`. Mark it
   as a pre-release while the integration is in testing. Every release needs a version that no
   earlier release used, whether it is a pre-release or a full release.

HACS offers a release as soon as it is published, so check that CI passed on the commit before
you publish. A pre-release reaches only the users who turned on the *Alacart Pre-release* switch.
Until the first full release, HACS installs the newest commit on `main` for every other user, so
merge to `main` only what is ready for testers.

The workflow `.github/workflows/release.yml` then runs these checks:

- The tag matches the version in the manifest.
- The commit is on `main`.
- Every check of the CI workflow passes.

If the workflow fails, delete the release, fix the problem, and release again.

## License

The integration is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
