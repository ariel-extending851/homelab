# Project Memory & Lessons Learned
>
> This file is automatically updated by the agent to store context, recurring issues, and environment specifics.

- **Infrastructure:** Oracle Cloud VM.Standard3.Flex 2 instances (2 cores, 12GB RAM).
- **Network:** Tailscale mesh is the primary connectivity method.
- **Constraints:** Raspberry Pi nodes have limited I/O; avoid heavy concurrent disk writes.
- SearXNG latency is bound by the slowest engine; aggressive timeouts (1.5s) are required for hybrid-cloud stability.
