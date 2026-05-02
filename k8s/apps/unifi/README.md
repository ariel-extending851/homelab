# UniFi Network Application (on-demand)

Stack to adopt and configure UniFi devices (e.g. Switch Flex Mini) without
running the controller 24/7. Both Deployments default to `replicas: 0` in
Git; flip them with `make unifi-up` / `make unifi-down`. The switch keeps
its provisioned config in flash and continues to forward traffic while the
controller is offline.

## Topology

- `unifi-db` — `mongo:7.0`, ClusterIP, RWO PVC `unifi-mongo-pvc` (5Gi).
- `unifi-network-application` — `linuxserver/unifi-network-application`,
  `hostNetwork: true`, RWO PVC `unifi-config-pvc` (2Gi).
- Credentials live in SOPS-encrypted `secret.yaml` (`unifi-credentials`).
- Mongo bootstrap user is created from `configmap.yaml` (`init-mongo.js`)
  on first start; the script reads `MONGO_USER` / `MONGO_PASS` from env.

ArgoCD ignores drift on `/spec/replicas` (see
`k8s/gitops/apps-root.yaml`), so manual scaling does not cause re-sync.

## Operating

```bash
make unifi-up       # scale db + controller to 1, prints https://<node-ip>:8443
make unifi-status   # show deploy/pod/pvc state
make unifi-down     # scale both to 0
```

After `make unifi-up`, wait ~60–90s for the JVM to finish booting, then
visit the printed URL. The cert is self-signed — accept it once.

## Node placement (operational invariant)

The controller pod runs with `hostNetwork: true` and is not pinned via
`nodeSelector`. The node it lands on **must share L2 with the UniFi
device** so UDP/10001 discovery broadcasts and UDP/3478 STUN traffic
arrive. If the switch never appears as "Pending Adoption":

1. Check which node took the pod:
   `kubectl -n unifi get pod -l app=unifi-network-application -o wide`
2. If that node is not on the switch's VLAN, cordon it and scale the
   controller again so it lands elsewhere, or add a `nodeSelector`.
3. Confirm UDP/3478 is free on the target node before scale-up:
   `ss -ulnp | grep 3478` (Tailscale STUN sometimes binds it).

## Switch adoption

1. `make unifi-up`, wait for the URL, complete the first-run wizard.
2. The Flex Mini appears under **Devices → Pending Adoption** in ~30s.
3. Click **Adopt**; wait for `Connected` / `Provisioned`.
4. Apply port profiles, VLANs, PoE settings.
5. `make unifi-down` when finished. The switch keeps its config.

## Troubleshooting

- **Switch stuck on "Managed by Other"** — SSH the device (`ubnt`/your
  password) and run `set-default` to factory-reset, then re-adopt.
- **PVC mongo restored from Velero with pre-existing data** —
  `init-mongo.js` only runs on an empty `/data/db`. Create the user
  manually:
  ```bash
  kubectl -n unifi exec -it deploy/unifi-db -- mongosh \
    -u root -p "$(kubectl -n unifi get secret unifi-credentials \
      -o jsonpath='{.data.MONGO_INITDB_ROOT_PASSWORD}' | base64 -d)" \
    --authenticationDatabase admin --eval '
      db.getSiblingDB("admin").createUser({
        user: "unifi", pwd: "<MONGO_PASS>",
        roles: [
          {role:"dbOwner",db:"unifi"},
          {role:"dbOwner",db:"unifi_stat"},
          {role:"dbOwner",db:"unifi_audit"},
          {role:"dbOwner",db:"unifi_dpia"}
        ]
      })'
  ```
- **CrashLoopBackOff on UDP/3478** — port collision with host (Tailscale
  STUN). Move the pod to another node or stop the conflicting service.
