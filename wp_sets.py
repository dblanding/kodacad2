"""wp_sets.py -- grouping EXISTING workplanes into a Workplane Set.

Session 181 (Doug's Linn Cove viaduct loft: a workplane on the end face of
every tenth segment, each with its face profile projected on it, then ONE
Loft through all of them). Until now a set could only be made by the
Create Workplane Set dialog, which creates NEW parallel workplanes, and
dropping existing workplanes onto a set node in the tree is refused (only
assemblies can hold children). This is the missing step: select workplanes
in the tree, right-click -> Make Workplane Set.

Pure bookkeeping on the main window's four dicts, so it can be tested
without Qt or OCCT:

  wp_dict        {wp_uid: WorkPlane}          (insertion order = creation)
  wp_set_dict    {set_uid: [wp_uid, ...]}     (list order = LOFT order)
  wp_parent_set  {wp_uid: set_uid}
  wp_names       {uid: user-chosen name}

The loft goes through the members in list order, so the order matters: the
members are put in CREATION order (wp3 before wp7 -- the order of wp_dict,
which is also the order the tree shows them), whatever order they were
clicked in. Make the workplanes in the order the loft should run.
"""


def next_set_uid(wp_set_dict):
    nums = [int(u[1:]) for u in wp_set_dict
            if u.startswith("s") and u[1:].isdigit()]
    return "s%i" % ((max(nums) if nums else 0) + 1)


def make_set(wp_dict, wp_set_dict, wp_parent_set, wp_names, uids):
    """Group the workplanes `uids` into a NEW set. Returns
    (set_uid, members, emptied_sets): the new set's uid, its members in
    creation order, and the uids of any old sets that were left empty
    (and so were removed) because their workplanes moved here.

    Raises ValueError (message fit for the status bar) if a uid is not a
    workplane or fewer than two are given; nothing is changed then. A
    workplane that already belongs to a set is MOVED out of it."""
    wanted = set(uids)
    unknown = [u for u in wanted if u not in wp_dict]
    if unknown:
        raise ValueError(
            f"'{sorted(unknown)[0]}' is not a workplane -- select only "
            f"workplanes.")
    members = [u for u in wp_dict if u in wanted]        # creation order
    if len(members) < 2:
        raise ValueError(
            "Select two or more workplanes (Ctrl/Shift-click in the "
            "tree), then right-click -> Make Workplane Set.")
    emptied = []
    for u in members:
        old = wp_parent_set.pop(u, None)
        if old is not None and old in wp_set_dict:
            if u in wp_set_dict[old]:
                wp_set_dict[old].remove(u)
            if not wp_set_dict[old]:
                del wp_set_dict[old]
                wp_names.pop(old, None)
                emptied.append(old)
    set_uid = next_set_uid(wp_set_dict)
    wp_set_dict[set_uid] = list(members)
    for u in members:
        wp_parent_set[u] = set_uid
    return set_uid, members, emptied
