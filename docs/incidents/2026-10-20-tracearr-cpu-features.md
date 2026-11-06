# Tracearr startup failure: virtual CPU feature masking

Date: 2026-10-20

## Evidence and cause

After a container update, Tracearr failed during startup in sharp 0.35.5 with:
`Unsupported CPU: Prebuilt binaries for linux x64 require v2 microarchitecture`.
The operator supplied pod status showing Tracearr on control-plane in Error while
its PostgreSQL and Redis pods were Running. Guest lscpu output reported
`QEMU Virtual CPU version 2.5+` and lacked sse4_2 (and other x86-64-v2 features).
Read-only TrueNAS API inspection showed CUSTOM CPU mode with no model selected.
The updated Tracearr image tag/digest was not captured.

The virtual CPU exposed an insufficient instruction set to the container.
Containers use the CPU features exposed by their Kubernetes node; installing
another npm package cannot expose instructions masked by the hypervisor.

## Requirement and recovery

The observed sharp Linux x64 binary requires x86-64-v2 capabilities, not merely
one CPU flag. Sharp's installation documentation lists SSE4.2 for Linux x64:
https://sharp.pixelplumbing.com/install/#prebuilt-binaries

For this deployment, use Host Passthrough CPU mode for the K3s master VM on its
current compatible host, or a deliberately selected CPU model that exposes all
required capabilities. Verify every node eligible to run Tracearr before future
image updates; checking only sse4_2 is not a complete x86-64-v2 validation.

Recovery performed by the operator: gracefully stop the K3s master VM, change
CPU mode to Host Passthrough in TrueNAS, save, and start the VM. This interrupts
the control plane and applications hosted on that VM. The operator confirmed
Tracearr worked afterward. Post-change logs and image digest were not captured
independently. No database or application-data changes were needed for this fix.

Host Passthrough ties guest CPU capabilities to the physical host; reassess
compatibility before moving the VM to different hardware.

## Verification after rebuilds or updates

On the K3s master:

```sh
lscpu | grep -E 'Model name|Flags'
kubectl -n tools get pods -o wide
kubectl -n tools logs deployment/tracearr --tail=50
```

Confirm the guest exposes the required CPU capabilities, Tracearr becomes Ready,
and the application opens normally. Capture the running image tag/digest for
future incident comparisons. The VM CPU setting is operational configuration;
it is not enforced by the Kubernetes manifests in this repository.
