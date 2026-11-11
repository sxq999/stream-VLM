# stream-VLM

Reusable streaming VLM experiment harness. Scope: model deployment, causal input replay, sessions, backend integration, observability and reproducible acceptance. Optimization research is out of scope.

The implementation contract is [TASK_SPEC.md](TASK_SPEC.md). Machine-readable milestones and acceptance requirements are in [task_manifest.json](task_manifest.json).

Implementation is in progress. A backend being configurable does not mean it has been deployed or validated. See [STATUS.md](STATUS.md) for measured capability status.

Model weights, source videos, secrets, machine-specific settings and full run artifacts are excluded from Git. Models and services must run in isolated environments; existing research environments remain untouched.
