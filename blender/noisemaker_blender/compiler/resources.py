"""resources.py -- texture pooling / register allocation.

Faithful port of the reference ``shaders/src/runtime/resources.js``: liveness
analysis + a Linear Scan Register Allocation over the expanded render passes.

The expander assigns every node-local output its own *virtual* texture id
(``node_<n>_out`` and friends). Many of these are short-lived -- written by one
pass, read by the next, then dead. ``allocateResources`` walks the pass timeline
and maps each virtual id to a reusable *physical* slot id (``phys_0``,
``phys_1`` ...), so a downstream pass can write into the slot a now-dead upstream
texture vacated. Globals (``global_*``) are infinite/pre-allocated and never
pooled -- they are simply omitted from the allocation map (the runtime treats an
unmapped id as itself; see ``runtime/graph_loader.Graph.phys``).

This drives the ``allocations`` field of the compiled graph. The slot a virtual
id lands in is parity-critical (the C#/Unity, three.js, etc. ports must agree on
``phys_N``), so the algorithm is reproduced exactly:

  * outputs are *defined* (allocated) at their pass index, reusing the first free
    slot whose last user finished in a *strictly earlier* pass (``availableAfter
    < i``), else minting a fresh ``phys_<count++>``;
  * inputs are *released* at the pass index that is the END of their lifetime,
    becoming available *after* that pass.

``freeList`` is a plain list used as the reference's array of
``{id, availableAfter}`` records; ``findIndex``/``splice`` are mirrored so the
*first* eligible slot (insertion order) is the one reused -- this ordering is
what makes the emitted ``phys_N`` assignment deterministic and matches every
sibling port.

stdlib-only and self-contained: no imports at all.
"""

from __future__ import annotations


def analyze_liveness(passes):
    """Lifetime ``{start, end}`` (pass indices) per virtual texture id.

    Port of ``analyzeLiveness``. Both inputs (read at index i) and outputs
    (written at index i) ``touch`` the texture, widening its [start, end]
    window. ``global_*`` ids are ignored -- they live forever.

    Returns
    -------
    dict
        ``{virtualId: {"start": int, "end": int}}`` in first-seen order.
    """
    lifetime = {}

    def touch(tex_id, index):
        if not tex_id:
            return
        # Ignore globals for liveness analysis (they are infinite).
        if tex_id.startswith("global_"):
            return
        if tex_id not in lifetime:
            lifetime[tex_id] = {"start": index, "end": index}
        else:
            entry = lifetime[tex_id]
            entry["start"] = min(entry["start"], index)
            entry["end"] = max(entry["end"], index)

    for index, pass_ in enumerate(passes):
        # Inputs are read at this index.
        inputs = pass_.get("inputs")
        if inputs:
            for tex in inputs.values():
                touch(tex, index)
        # Outputs are written at this index.
        outputs = pass_.get("outputs")
        if outputs:
            for tex in outputs.values():
                touch(tex, index)

    return lifetime


def allocate_resources(passes):
    """Map each virtual texture id to a physical pool slot (``phys_N``).

    Port of ``allocateResources`` -- a Linear Scan Register Allocation walking
    the pass timeline. ``global_*`` ids are never allocated (omitted from the
    result). Returns a plain ``dict`` (the reference returns a ``Map``; the
    caller serialises it to an object) preserving allocation order.

    Returns
    -------
    dict
        ``{virtualId: "phys_N"}`` in allocation (first-define) order.
    """
    lifetime = analyze_liveness(passes)
    allocations = {}
    # freeList: list of {"id": str, "availableAfter": int}.
    free_list = []
    physical_count = 0

    # Simulate the timeline pass by pass.
    for i, pass_ in enumerate(passes):
        # 1. Allocate Outputs (Definitions).
        outputs = pass_.get("outputs")
        if outputs:
            for tex_id in outputs.values():
                if tex_id.startswith("global_"):
                    continue  # Globals are pre-allocated.
                if tex_id in allocations:
                    continue

                # Find the first free slot released in a strictly earlier pass.
                # We are currently AT step i, so anything that finished BEFORE i
                # (availableAfter < i) may be reused.
                free_idx = -1
                for idx, item in enumerate(free_list):
                    if item["availableAfter"] < i:
                        free_idx = idx
                        break

                if free_idx != -1:
                    # Reuse.
                    item = free_list.pop(free_idx)
                    allocations[tex_id] = item["id"]
                else:
                    # Allocate new.
                    phys_id = "phys_%d" % physical_count
                    physical_count += 1
                    allocations[tex_id] = phys_id

        # 2. Release Inputs (Last Uses).
        inputs = pass_.get("inputs")
        if inputs:
            for tex_id in inputs.values():
                if tex_id.startswith("global_"):
                    continue
                entry = lifetime.get(tex_id)
                # If this pass is the END of the texture's life, release it.
                if entry and entry["end"] == i:
                    phys_id = allocations.get(tex_id)
                    if phys_id:
                        # Becomes available AFTER this pass is done.
                        free_list.append({"id": phys_id, "availableAfter": i})

    return allocations
