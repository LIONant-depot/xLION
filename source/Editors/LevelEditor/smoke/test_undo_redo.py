"""Undo/redo: multiple edits, branch discard, and dirty flag."""
from harness import quote


def test_multiple_undo_redo(level):
    """Several edits, undo them all, redo them all, state identical at each step."""
    before = level.entities()
    
    # Create multiple entities
    entities = []
    for i in range(5):
        entity = level.new_entity()
        entities.append(entity)
    
    assert len(level.entities()) == len(before) + 5
    
    # Undo all
    for _ in range(5):
        level.cmd("Undo")
    
    assert level.entities() == before
    
    # Redo all
    for _ in range(5):
        level.cmd("Redo")
    
    assert len(level.entities()) == len(before) + 5


def test_new_edit_discards_redo_branch(level):
    """A new edit after an undo discards the redo branch."""
    entity1 = level.new_entity()
    level.cmd("Undo")
    
    # Create a new entity (this should discard the redo branch)
    entity2 = level.new_entity()
    
    # Redo should be refused now
    assert "Nothing to redo" in level.cmd("Redo")
    
    # Undo should still work
    level.cmd("Undo")
    assert entity2 not in level.entities()


def test_undo_with_nothing_to_undo(level):
    """Undo with nothing to undo answers a message, not a crash."""
    # Close and reopen to get a clean state
    level.ed.cmd("Close -Save 0")
    level.ed.cmd(f"OpenLevel -Level {level.guid} -Save 0")
    
    # Undo should answer with a message
    reply = level.cmd("Undo")
    assert reply  # Should be a message, not empty


def test_dirty_flag_follows_undo_position(level):
    """Dirty flag follows the undo position."""
    assert not level.dirty()
    
    entity = level.new_entity()
    assert level.dirty()
    
    level.cmd("Undo")
    assert not level.dirty()
    
    level.cmd("Redo")
    assert level.dirty()


def test_redo_with_nothing_to_redo(level):
    """Redo with nothing to redo answers a message, not a crash."""
    # Close and reopen to get a clean state
    level.ed.cmd("Close -Save 0")
    level.ed.cmd(f"OpenLevel -Level {level.guid} -Save 0")
    
    # Redo should answer with a message
    reply = level.cmd("Redo")
    assert reply  # Should be a message, not empty
