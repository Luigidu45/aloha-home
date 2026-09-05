# Relay hosting

The relay on your own server, under your own name: robots dial out to it with a key, operators open it in a browser with a token, and the cockpit works from anywhere. This guide takes a fresh Ubuntu VM and a domain to `https://dimos-relay.example.com`. The relay itself needs nothing new; everything here is packaging: a container image ([`docker/relay/Dockerfile`](/docker/relay/Dockerfile)), a compose file ([`docker/relay/compose.yaml`](/docker/relay/compose.yaml)), and the steps around them. The flags it uses are explained in [Web SDK](/docs/usage/web_sdk.md).

## 1. What you get, and what you do not

- One relay process on one machine. The registry is in memory: after a restart every robot re-registers by itself within seconds and every open page reconnects.
- No accounts. The auth file holds robot keys, each bound to one robot id, and viewer tokens. A viewer token does everything (view, teleop, publish) on every robot behind the relay, so hand tokens out like passwords.
- The relay terminates TLS itself, on one port for HTTPS (TCP) and QUIC (UDP). No reverse proxy: an HTTP proxy cannot carry QUIC, and the relay advertises the WebTransport URL from the host the client dialed.
- The certificate and the auth file are read at startup. Changing either means a restart, which costs a few seconds of reconnection.

## 2. DNS and firewall

Point an A record at the VM (`dimos-relay.example.com -> <public IP>`). Open 443 TCP, 443 UDP, and 80 TCP for certbot (nothing listens on 80 between renewals). The cloud provider's own firewall (security group) needs the same rules; UDP 443 is the one people forget.

```bash
sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp && sudo ufw allow 443/udp
sudo ufw enable
```

Without UDP 443 there is no WebTransport and, by design, no fallback: the page loads and never connects.

## 3. Certificate

Clone dimos onto the VM (the image is built from the checkout) and install Docker and certbot. Request the certificate with a deploy hook that installs the two PEM files into the relay's config directory, owned by uid 1993 (the image's `deno` user), and restarts the relay:

```bash
sudo apt install -y git certbot docker.io docker-compose-v2
sudo git clone https://github.com/dimensionalOS/dimos /srv/dimos
sudo mkdir /srv/dimos/docker/relay/config
sudo certbot certonly --standalone -d dimos-relay.example.com --deploy-hook \
  'install -o 1993 -g 1993 -m 600 "$RENEWED_LINEAGE"/fullchain.pem "$RENEWED_LINEAGE"/privkey.pem /srv/dimos/docker/relay/config/ && docker compose -f /srv/dimos/docker/relay/compose.yaml restart relay'
```

The hook runs now (so `config/` holds `fullchain.pem` and `privkey.pem`; the restart is a no-op until the relay exists) and certbot saves it in the renewal configuration: every automatic renewal (certbot's timer, roughly every 60 days) installs the new files and restarts the relay, which reads certificates only at startup. `sudo certbot renew --dry-run` checks renewal but skips hooks, so rehearse the restart once by running the hook command by hand after step 5.

## 4. Auth file

`config/auth.json` maps robot ids to keys and viewer names to tokens, each 16 to 256 characters and no secret used twice. Generate them with `openssl rand -hex 32`:

```json
{
  "robots": { "go2-lab": "<key>" },
  "viewers": { "paul": "<token>" }
}
```

```bash
sudo chown 1993:1993 /srv/dimos/docker/relay/config/auth.json
sudo chmod 600 /srv/dimos/docker/relay/config/auth.json
```

A robot id here has to match the robot's `--robot-id` (its hostname when not given). Adding or rotating a secret is an edit plus `docker compose restart relay`. The relay refuses a malformed file with a message that names the entry, never the secret, and it never logs secrets.

## 5. Run

```bash
cd /srv/dimos/docker/relay
sudo docker compose up -d --build
curl https://dimos-relay.example.com/api/info
sudo docker compose logs -f relay
```

The first build takes a few minutes: Deno installs the web dependencies and builds the SDK and the cockpit inside the image. `/api/info` answers `{"wtUrl":"https://dimos-relay.example.com","v":...}`. The log opens with the ready line and then shows connections (`[relay] robot connected`, `[relay] viewer 1 authenticated as paul`), rejections with their reason (`[relay] robot go2-lab rejected: invalid robot key`), and `[relay] robot go2-lab disconnected` when one leaves. `restart: unless-stopped` brings the relay back after a reboot. A new dimos version is `git pull` and the same `up -d --build`.

## 6. Robot

The robot needs the key bound to its id, from the environment or the `.env` file of the checkout it runs from (the `--relay-key` flag exists but shows in the process list):

```bash
RELAY_KEY=<key> dimos run unitree-go2 --relay-url https://dimos-relay.example.com --robot-id go2-lab
```

It dials out, so it works behind NAT with no open ports. A wrong key is logged once as `auth_failed` and the bridge gives up rather than retrying: fix `RELAY_KEY` and start again.

## 7. Operator

Open `https://dimos-relay.example.com/`. The page asks for a viewer token, keeps it in the browser's local storage, and "Log out" in the status bar forgets it. With several robots registered the page lists them; "switch robot" reopens the list. `/api/stats` (per-robot, per-channel, and per-viewer counters, with viewer names) takes the same token as a bearer:

```bash
curl -H "Authorization: Bearer <token>" https://dimos-relay.example.com/api/stats
```

## 8. Without Docker

The same relay under systemd: the pinned Deno, a checkout owned by a service user, the built dists, and the right to bind 443.

```bash
sudo apt install -y git unzip
curl -fsSLo /tmp/deno.zip https://github.com/denoland/deno/releases/download/v2.6.10/deno-x86_64-unknown-linux-gnu.zip
sudo unzip -o -d /usr/local/bin /tmp/deno.zip
sudo useradd --system --create-home --home /srv/relay relay
sudo -u relay git clone https://github.com/dimensionalOS/dimos /srv/relay/dimos
sudo -u relay sh -c 'cd /srv/relay/dimos/web && deno install --frozen && deno task -r build'
sudo mkdir /etc/relay
```

The pin is `DENO_VERSION` in [`dimos/utils/deno.py`](/dimos/utils/deno.py#L32); an arm64 VM downloads `deno-aarch64-unknown-linux-gnu.zip` instead. Put `auth.json` in `/etc/relay` owned by `relay` with mode 600, and use `install -o relay -g relay -m 600 "$RENEWED_LINEAGE"/fullchain.pem "$RENEWED_LINEAGE"/privkey.pem /etc/relay/ && systemctl restart dimos-relay` as the certbot deploy hook. `/etc/systemd/system/dimos-relay.service`:

```ini
[Unit]
Description=dimos relay
After=network-online.target

[Service]
User=relay
WorkingDirectory=/srv/relay/dimos/web
ExecStart=/usr/local/bin/deno run --frozen --allow-net --allow-read=/srv/relay/dimos/web,/etc/relay relay/main.ts --host 0.0.0.0 --port 443 --cockpit-dir cockpit/dist --sdk-dir sdk/dist --cert /etc/relay/fullchain.pem --key /etc/relay/privkey.pem --auth-file /etc/relay/auth.json
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now dimos-relay`, then `journalctl -u dimos-relay -f` for the log.

## 9. LAN without a domain

On a LAN with no public name, sign your own certificate: mkcert creates a private CA (`mkcert -install` also adds it to the browsers on that machine) and a certificate for the relay's address. The robot trusts the CA through `--relay-ca`. The auth file stays mandatory: the relay binds a non-loopback address only with certificate, key, and auth file together.

For this direct Deno run, use a checkout owned by your user. Create `docker/relay/config/auth.json` with the format in section 4, owned by your user with mode 600 (Docker's uid 1993 is only for the container). From the repository root:

```bash
cd web
deno install --frozen && deno task -r build
mkcert -install && mkcert 192.168.1.20
deno task dev --host 192.168.1.20 --cert 192.168.1.20.pem --key 192.168.1.20-key.pem \
  --auth-file ../docker/relay/config/auth.json --cockpit-dir cockpit/dist --sdk-dir sdk/dist
```

On the robot, with the relay's mkcert CA installed:

```bash
RELAY_KEY=<key> dimos run unitree-go2 --relay-url https://192.168.1.20:7780 \
  --relay-ca "$(mkcert -CAROOT)/rootCA.pem" --robot-id go2-lab
```

(The compose file works here too, with the mkcert files in `config/` as `fullchain.pem` and `privkey.pem`.) Browsers are the catch. Firefox verifies a private root for QUIC only with `network.http.http3.disable_when_third_party_roots_found` set to `false` in `about:config`. Chromium refuses private roots for QUIC outright (`QUIC_CERT_ROOT_NOT_KNOWN`; no flag lifts it): the page loads over HTTPS and never connects. Chromium on a LAN needs a publicly trusted certificate, which a domain you own provides without any inbound port: point a name at the LAN address and use certbot's DNS challenge (`certbot certonly --manual --preferred-challenges dns -d relay.lan.example.com`).

## 10. Troubleshooting

- **`auth_failed`.** The relay's message says `missing` (the client sent no secret: `RELAY_KEY` not in the robot's environment, no token stored in the browser) or `invalid` (wrong secret, or a robot key used with another robot id). It is terminal: the bridge stops and the page shows the token form. Fix the secret and start the client again. The relay log names the rejected robot id or viewer.
- **Certificate errors.** Check the VM clock (`timedatectl`). The robot fails with `CERTIFICATE_VERIFY_FAILED` when the relay serves `cert.pem` instead of `fullchain.pem` (browsers fetch the missing intermediate, OpenSSL does not) or when `--relay-ca` points at the wrong CA.
- **UDP 443 blocked.** HTTPS works, the page loads and stays "reconnecting", the robot's startup attempts time out (`relay startup connection attempt N failed`) and it gives up. Check both firewalls for UDP; `sudo ss -ulnp | grep 443` on the VM shows the published UDP port.
- **Robot behind NAT.** Fine: it dials out, and the QUIC session sends keepalives every 4 s.
- **Relay behind NAT** (a home server). Forward TCP 443 and UDP 443 to it. `/api/info` advertises the name the client dialed, so nothing else changes.
- **Restarts.** `docker compose restart relay` is always safe: robots re-register within seconds, pages reconnect on their own. A robot killed without a clean close holds its id for up to 30 s (the QUIC idle timeout); its restart waits that out.

## 11. Checklist

What a hosted relay is verified with; repeat it after changes to the relay, the image, or this guide.

- [ ] Fresh Ubuntu VM with a domain, sections 2 to 5 top to bottom; `curl https://.../api/info` from a laptop.
- [ ] Replay robot on another, NATed network (`dimos --replay run unitree-go2 --relay-url ...`).
- [ ] Laptop on a third network, in Chromium and in Firefox: wrong token rejected, right token connects; robot picker with two robots; live map and video; teleop drives the replay robot.
- [ ] `docker compose restart relay` with the page open: the page reconnects, the robot re-registers.
- [ ] The deploy hook by hand: the relay restarts with the installed files; `sudo certbot renew --dry-run` passes.
- [ ] `/api/stats`: 401 without the token, 200 with it.
