# Rollback and preservation

vitanx is a newly created directory, not an overlay or modification to either
source project. No global launcher, environment profile, original application,
ROM or save location is changed. To stop using it, close its generated diagnostic
app and leave this directory unused. To reverse installation without deletion,
rename ~/Developer/vitanx to ~/Developer/vitanx.disabled. There is no source
project to restore. No original checkpoint should be restored for this task.

The workspace outputs contain a SHA256-verified source checkpoint tarball.
Restore only into a new empty directory; compare the adjacent checksum first.
The source inventory (evidence/source-before.json) and after-check compare the
selected code/documentation files from VitaXNative, NXNative-next and stable
NXNative. This is a source-preservation check, not a hash audit of all ROMs or saves;
those locations were never opened or modified by this task.

All smoke outputs are confined to builds/plaintext-smoke. The explicit smoke run
sets VX_SAVE_ROOT to its build-local saves directory. Future manual app runs use
the isolated vitanx namespace. Nothing was installed in Applications.
