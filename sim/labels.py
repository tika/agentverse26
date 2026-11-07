"""Exactly three training classes, plus package identity taxonomy on every target."""

def label_drum(stage,entry):
    from isaacsim.core.experimental.utils.semantics import add_labels
    # Root label is inherited by body/lid/plate hardware, giving ONE complete drum box.
    # Defects are separate under /World/Defects, so cannot inherit the drum class.
    prim=stage.GetPrimAtPath(entry['prim_path'])
    add_labels(prim,labels=['drum'],taxonomy='class')
    add_labels(prim,labels=[entry['id']],taxonomy='drum_id')
    for defect in entry['defects']:
        prim=stage.GetPrimAtPath(defect['prim_path'])
        add_labels(prim,labels=[defect['type']],taxonomy='class')
        add_labels(prim,labels=[entry['id']],taxonomy='drum_id')


def label_scene(stage,entries):
    for entry in entries: label_drum(stage,entry)
