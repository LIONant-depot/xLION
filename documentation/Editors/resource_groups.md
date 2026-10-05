# Resource groups and the "+" of the resource view

Every resource type has a **group**, like every component has a category. The group, and a sentence saying what the resource is, are declared by the plugin, in its `Plugin.config/resource_pipeline.config.txt`:

```
  "PipelinePlugin/TypeName"                  ;string "Font"
  "PipelinePlugin/Group"                     ;string "Graphics"
  "PipelinePlugin/Description"               ;string "A TrueType or OpenType font baked into an atlas (...) for the Text component."
```

(`Group` and `Description` are fields of `asset_plugins_db::pipeline_plugin`. Remember to raise the `[ xProperties : N ]` count of the file when rows are added.)

A plugin without a `Group` is still loaded, under **Other**, so its resource type does not disappear, but the editor reports it as an error and `test_resource_groups.py` fails.

The groups today: Graphics (Texture, Material, MaterialInstance, Font), Geometry (Geom, GeomStatic, GeomSkin), Animation (Skeleton, AnimPackage), World (Level, Scene, Prefab), Game (Game, ScriptModule,
SharedComponentTemplate), Physics (PhysicsMaterial), Organization (Folder).

## The "+" popup

The popup is **`xeditor::RenderGroupedList`** (`dependencies/xeditor/include/xeditor/grouped_list.h`), the one "add something" popup of the editors: the Add Component popup of the Entity Properties
(`xscene_panel_component_selector.h`) and this one only say what the items are (name, group, icon, hint). The look and the behavior - and any bug - are in that one place. It fixes the size of what is
inside (a popup resizes itself to its content every frame, so a search box and a list that took their size from the window shrank the popup when nothing matched, and it stayed small). It has: a search box (focused when it opens), then the types by group - each group collapsible, with how many types it has, open while
searching, its open/closed state remembered - and a hint on each type (its name, its description, its group). The search looks at the type name and at the group. The popup opens under the button, not at the
mouse. Choosing a type creates the resource in the current folder, as before.

Code: `xeditor::RenderGroupedList`; the items of the resources are built by `virtual_tree_tab::AddResourcePopUp` (`xresource_editor_asset_browser_virtual_tree_tab.h`). Tests: `test_resource_groups.py`.
