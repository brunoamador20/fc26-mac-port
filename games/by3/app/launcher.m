/* Bayonetta 3 launcher: a settings window with presets, then the game.
   The app is a small bundle; the game's data stay in the work folder (BY3_build) named by Info.plist's BY3WorkFolder,
   so nothing large is copied. Settings are remembered in the app's preferences (org.macnativegames.by3).
   What each setting does in the runtime:
   - Frame rate: 30 = the game's own pacing (30 / 60 by scene); 60 = the 60 fps patch; 120 = the 60 fps patch on a 120 Hz
     present base (experimental: correct only if the game advances by real time, not by frames).
   - Internal resolution: dynamic (the game's own) or fixed 900p (the "Force Scaling 900p" patch).
   - Display: window (with a size) or macOS full screen.
   - Extras: improved LOD, no film grain (patches).
   Patches come from <work>/patches (scripts/prepare_patches.py); a missing one is left out and the window says so. */
#import <Cocoa/Cocoa.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>

static BOOL spanish(void) { return [NSLocale.preferredLanguages.firstObject hasPrefix:@"es"]; }
#define T(es, en) (spanish() ? @es : @en)

typedef struct { const char *name_es, *name_en; int fps, fixed900, fullscreen, lod, nograin, size; } Preset;
static const Preset presets[] = {
    {"Original (30 fps, como en la consola)", "Original (30 fps, as on the console)", 30, 0, 0, 0, 0, 2},
    {"Recomendado (60 fps)", "Recommended (60 fps)", 60, 0, 0, 0, 0, 2},
    {"Rendimiento (60 fps, 900p fijo)", "Performance (60 fps, fixed 900p)", 60, 1, 0, 0, 0, 2},
    {"Calidad (60 fps, 900p, LOD mejorado, sin grano, pantalla completa)", "Quality (60 fps, 900p, better LOD, no grain, full screen)", 60, 1, 1, 1, 1, 2},
};
enum { NPRESETS = sizeof presets / sizeof *presets };
static const int fps_values[] = {30, 60, 120};
static const int sizes[][2] = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440}};

@interface Launcher : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property NSWindow *window; @property NSPopUpButton *preset, *size, *internal; @property NSSegmentedControl *fps, *display;
@property NSButton *lod, *grain, *hud, *play; @property NSPopUpButton *mod; @property NSArray<NSString *> *mods; @property NSTextField *note; @property BOOL applying, launch;
@end

static NSString *work_folder(void) {
    NSString *w = [NSBundle.mainBundle objectForInfoDictionaryKey:@"BY3WorkFolder"];
    const char *e = getenv("BY3_WORK");
    return e && *e ? @(e) : w;
}
/* RomFS mods: <work>/../mods/<name>/romfs with a manifest.tsv (../totk/scripts/make_mod_manifest.py, or make mods). */
static NSString *mods_folder(void) { return [[work_folder() stringByDeletingLastPathComponent] stringByAppendingPathComponent:@"mods"]; }
static NSArray<NSString *> *romfs_mods(void) {
    NSMutableArray *out = [NSMutableArray array];
    for (NSString *name in [[NSFileManager.defaultManager contentsOfDirectoryAtPath:mods_folder() error:nil] sortedArrayUsingSelector:@selector(compare:)])
        if ([NSFileManager.defaultManager fileExistsAtPath:[mods_folder() stringByAppendingFormat:@"/%@/romfs/manifest.tsv", name]]) [out addObject:name];
    return out;
}
static BOOL have_patch(NSString *slug) {
    return [NSFileManager.defaultManager fileExistsAtPath:[work_folder() stringByAppendingFormat:@"/patches/%@.tsv", slug]];
}

@implementation Launcher
- (NSTextField *)label:(NSString *)s { NSTextField *l = [NSTextField labelWithString:s]; l.alignment = NSTextAlignmentRight; return l; }
- (void)applicationDidFinishLaunching:(NSNotification *)n {
    (void)n;
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    self.preset = [NSPopUpButton new];
    for (int i = 0; i < NPRESETS; i++) [self.preset addItemWithTitle:spanish() ? @(presets[i].name_es) : @(presets[i].name_en)];
    [self.preset addItemWithTitle:T("Personalizado", "Custom")];
    self.preset.target = self; self.preset.action = @selector(presetChanged:);
    self.fps = [NSSegmentedControl segmentedControlWithLabels:@[@"30", @"60", T("120 (experimental)", "120 (experimental)")]
                                                 trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changed:)];
    self.internal = [NSPopUpButton new];
    [self.internal addItemsWithTitles:@[T("Dinámica (la del juego)", "Dynamic (the game's own)"), T("900p fija", "Fixed 900p")]];
    self.internal.target = self; self.internal.action = @selector(changed:);
    self.display = [NSSegmentedControl segmentedControlWithLabels:@[T("Ventana", "Window"), T("Pantalla completa", "Full screen")]
                                                     trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changed:)];
    self.size = [NSPopUpButton new];
    for (unsigned i = 0; i < sizeof sizes / sizeof *sizes; i++) [self.size addItemWithTitle:[NSString stringWithFormat:@"%d × %d", sizes[i][0], sizes[i][1]]];
    self.size.target = self; self.size.action = @selector(changed:);
    self.lod = [NSButton checkboxWithTitle:T("LOD mejorado (más detalle a distancia)", "Improved LOD (more distant detail)") target:self action:@selector(changed:)];
    self.grain = [NSButton checkboxWithTitle:T("Quitar el grano de película", "Remove film grain") target:self action:@selector(changed:)];
    self.hud = [NSButton checkboxWithTitle:T("Mostrar FPS y resolución (tecla 1 lo oculta)", "Show FPS and resolution (key 1 hides it)") target:self action:@selector(changed:)];
    self.mod = [NSPopUpButton new]; [self.mod addItemWithTitle:T("Ninguno", "None")]; self.mods = romfs_mods();
    for (NSString *m in self.mods) [self.mod addItemWithTitle:m];
    self.mod.target = self; self.mod.action = @selector(changed:);
    self.note = [NSTextField wrappingLabelWithString:@""]; self.note.textColor = NSColor.secondaryLabelColor; self.note.font = [NSFont systemFontOfSize:11];
    self.play = [NSButton buttonWithTitle:T("Jugar", "Play") target:self action:@selector(start:)]; self.play.keyEquivalent = @"\r";
    NSButton *quit = [NSButton buttonWithTitle:T("Salir", "Quit") target:NSApp action:@selector(terminate:)]; quit.keyEquivalent = @"\033";

    NSGridView *grid = [NSGridView gridViewWithViews:@[
        @[[self label:T("Preset", "Preset")], self.preset],
        @[[self label:T("Fotogramas por segundo", "Frame rate")], self.fps],
        @[[self label:T("Resolución interna", "Internal resolution")], self.internal],
        @[[self label:T("Pantalla", "Display")], self.display],
        @[[self label:T("Tamaño de la ventana", "Window size")], self.size],
        @[[self label:T("Mejoras", "Extras")], self.lod],
        @[NSGridCell.emptyContentView, self.grain],
        @[[self label:T("Mod de interfaz", "Interface mod")], self.mod],
        @[[self label:T("Información", "Info")], self.hud],
    ]];
    grid.rowSpacing = 10; grid.columnSpacing = 12; [grid columnAtIndex:0].xPlacement = NSGridCellPlacementTrailing;
    NSStackView *buttons = [NSStackView stackViewWithViews:@[quit, self.play]];
    NSStackView *stack = [NSStackView stackViewWithViews:@[grid, self.note, buttons]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical; stack.alignment = NSLayoutAttributeTrailing; stack.spacing = 16;
    stack.edgeInsets = NSEdgeInsetsMake(20, 20, 20, 20);
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 640, 360) styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                                                backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"Bayonetta 3"; self.window.contentView = stack; self.window.delegate = self;
    [self.note.widthAnchor constraintEqualToConstant:560].active = YES;

    NSInteger p = [d objectForKey:@"preset"] ? [d integerForKey:@"preset"] : 1;
    if (p >= 0 && p < NPRESETS) [self applyPreset:(int)p];
    else { [self.preset selectItemAtIndex:NPRESETS]; [self load:d]; }
    [self loadCommon:d];
    [self refresh];
    [self.window center]; [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
}
- (void)load:(NSUserDefaults *)d {
    int fps = (int)[d integerForKey:@"fps"]; self.fps.selectedSegment = fps == 120 ? 2 : fps == 30 ? 0 : 1;
    [self.internal selectItemAtIndex:[d boolForKey:@"fixed900"]]; self.display.selectedSegment = [d boolForKey:@"fullscreen"];
    NSInteger s = [d objectForKey:@"size"] ? [d integerForKey:@"size"] : 2; [self.size selectItemAtIndex:s >= 0 && s < 4 ? s : 2];
    self.lod.state = [d boolForKey:@"lod"]; self.grain.state = [d boolForKey:@"nograin"];
}
- (void)loadCommon:(NSUserDefaults *)d {   // not part of presets
    self.hud.state = [d objectForKey:@"hud"] ? [d boolForKey:@"hud"] : YES;
    NSString *m = [d stringForKey:@"mod"]; NSUInteger i = m ? [self.mods indexOfObject:m] : NSNotFound;
    [self.mod selectItemAtIndex:i == NSNotFound ? 0 : (NSInteger)i + 1];
}
- (void)applyPreset:(int)i {
    const Preset *p = &presets[i]; self.applying = YES;
    [self.preset selectItemAtIndex:i]; self.fps.selectedSegment = p->fps == 30 ? 0 : p->fps == 60 ? 1 : 2;
    [self.internal selectItemAtIndex:p->fixed900]; self.display.selectedSegment = p->fullscreen; [self.size selectItemAtIndex:p->size];
    self.lod.state = p->lod; self.grain.state = p->nograin; self.applying = NO;
}
- (void)presetChanged:(id)sender { (void)sender; NSInteger i = self.preset.indexOfSelectedItem; if (i < NPRESETS) [self applyPreset:(int)i]; [self refresh]; }
- (void)changed:(id)sender { if (!self.applying && sender != self.hud && sender != self.mod) [self.preset selectItemAtIndex:NPRESETS]; [self refresh]; }
- (void)refresh {
    self.size.enabled = self.display.selectedSegment == 0;
    NSMutableArray *missing = [NSMutableArray array];
    if (self.fps.selectedSegment > 0 && !have_patch(@"60fps")) [missing addObject:@"60fps"];
    if (self.internal.indexOfSelectedItem == 1 && !have_patch(@"force-scaling-900p-v3")) [missing addObject:@"Force Scaling 900p v3"];
    if (self.lod.state && !have_patch(@"improved-lod-v2")) [missing addObject:@"Improved LOD v2"];
    if (self.grain.state && !have_patch(@"remove-film-grain")) [missing addObject:@"Remove Film Grain"];
    NSMutableString *s = [NSMutableString string];
    if (self.fps.selectedSegment == 2)
        [s appendString:T("120 fps es experimental: si el juego se ve acelerado, vuelve a 60. ", "120 fps is experimental: if the game looks sped up, go back to 60. ")];
    if (missing.count)
        [s appendFormat:T("Faltan estos parches y se omitirán: %@ (ponlos en mods/1.2.0 y corre scripts/prepare_patches.py).",
                          "These patches are missing and will be left out: %@ (put them in mods/1.2.0 and run scripts/prepare_patches.py)."),
                          [missing componentsJoinedByString:@", "]];
    if (!work_folder() || ![NSFileManager.defaultManager isExecutableFileAtPath:[work_folder() stringByAppendingPathComponent:@"build/by3-native"]]) {
        [s appendFormat:T("No encuentro el juego en %@.", "The game is not in %@."), work_folder() ?: @"?"]; self.play.enabled = NO;
    }
    self.note.stringValue = s; self.note.hidden = !s.length;
}
- (void)save {
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    [d setInteger:self.preset.indexOfSelectedItem forKey:@"preset"];
    [d setInteger:fps_values[self.fps.selectedSegment] forKey:@"fps"]; [d setBool:self.internal.indexOfSelectedItem == 1 forKey:@"fixed900"];
    [d setBool:self.display.selectedSegment == 1 forKey:@"fullscreen"]; [d setInteger:self.size.indexOfSelectedItem forKey:@"size"];
    [d setBool:self.lod.state forKey:@"lod"]; [d setBool:self.grain.state forKey:@"nograin"];
    [d setBool:self.hud.state forKey:@"hud"];
    if (self.mod.indexOfSelectedItem > 0) [d setObject:self.mods[self.mod.indexOfSelectedItem - 1] forKey:@"mod"]; else [d removeObjectForKey:@"mod"];
}
- (void)start:(id)sender { (void)sender; [self save]; self.launch = YES; [NSApp stop:nil]; [self.window orderOut:nil];
    NSEvent *e = [NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0 context:nil subtype:0 data1:0 data2:0];
    [NSApp postEvent:e atStart:YES]; }
- (void)windowWillClose:(NSNotification *)n { (void)n; if (!self.launch) [NSApp terminate:nil]; }
@end

static void fail(NSString *s) {
    NSAlert *a = [NSAlert new]; a.messageText = T("Bayonetta 3 no pudo arrancar", "Bayonetta 3 could not start"); a.informativeText = s; [a runModal];
}
static BOOL make_dir(NSString *p) { return [NSFileManager.defaultManager createDirectoryAtPath:p withIntermediateDirectories:YES attributes:nil error:nil]; }

int main(int argc, char **argv) {
    (void)argc; (void)argv;
    @autoreleasepool {
        [NSApplication sharedApplication]; NSApp.activationPolicy = NSApplicationActivationPolicyRegular;
        Launcher *l = [Launcher new]; NSApp.delegate = l;
        [NSApp run];
        if (!l.launch) return 0;
        NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
        NSString *work = work_folder(), *home = NSHomeDirectory();
        NSString *data = [home stringByAppendingPathComponent:@"Library/Application Support/MacNativeGames/BY3"];
        NSString *logs = [home stringByAppendingPathComponent:@"Library/Logs/MacNativeGames"];
        NSString *profile = [data stringByAppendingPathComponent:@"profile"], *slot = [data stringByAppendingPathComponent:@"game-slot"];
        if (!make_dir(profile) || !make_dir(slot) || !make_dir(logs)) { fail([NSString stringWithFormat:@"%@", data]); return 1; }
        if (chdir(work.fileSystemRepresentation)) { fail(work); return 1; }   // the runtime reads extracted/ and rewritten/ relative to it

        int fps = (int)[d integerForKey:@"fps"]; NSMutableArray *patches = [NSMutableArray array];
        if (fps >= 60 && have_patch(@"60fps")) [patches addObject:@"60fps"];
        if ([d boolForKey:@"fixed900"] && have_patch(@"force-scaling-900p-v3")) [patches addObject:@"force-scaling-900p-v3"];
        if ([d boolForKey:@"lod"] && have_patch(@"improved-lod-v2")) [patches addObject:@"improved-lod-v2"];
        if ([d boolForKey:@"nograin"] && have_patch(@"remove-film-grain")) [patches addObject:@"remove-film-grain"];
        setenv("BY3_PATCHES", [patches componentsJoinedByString:@","].UTF8String, 1);
        setenv("DM_PRESENT_HZ", fps == 120 ? "120" : "60", 1);
        if ([d boolForKey:@"fullscreen"]) setenv("BY3_FULLSCREEN", "1", 1);
        NSInteger s = [d integerForKey:@"size"]; if (s < 0 || s > 3) s = 2;
        setenv("TOTK_WINDOW_SIZE", [NSString stringWithFormat:@"%dx%d", sizes[s][0], sizes[s][1]].UTF8String, 1);
        if ([d boolForKey:@"hud"]) setenv("BY3_HUD_RENDER", "1", 1); else setenv("TOTK_FPS_OVERLAY", "0", 1);
        NSString *mod = [d stringForKey:@"mod"];
        if (mod && [romfs_mods() containsObject:mod]) setenv("TOTK_ROMFS_MODS", [mods_folder() stringByAppendingFormat:@"/%@/romfs", mod].fileSystemRepresentation, 1);
        else setenv("TOTK_ROMFS_MODS", "0", 1);

        setenv("TOTK_PROFILE_DIR", profile.fileSystemRepresentation, 1);
        setenv("TOTK_GAME_SLOT_DIR", slot.fileSystemRepresentation, 1);
        setenv("TOTK_ROMFS_PROOF_DIR", data.fileSystemRepresentation, 1);
        NSString *preferred = NSLocale.preferredLanguages.firstObject; if (preferred) setenv("TOTK_LOCALE", preferred.UTF8String, 1);
        setenv("TOTK_GPU_ALLOW_SUBMIT", "1", 1); setenv("TOTK_GPU_WIDEN", "1", 1); setenv("TOTK_GPU_BLOCKRT", "1", 1);
        setenv("TOTK_GPU_MIDCLEAR", "1", 1); setenv("TOTK_GPU_BUDGET_MB", "5000", 1);
        setenv("TOTK_SLOT_OWNER", "user", 1); setenv("TOTK_SLOT_PURPOSE", "player", 1);
        unsetenv("TOTK_HEADLESS");
        { NSString *cmds = [data stringByAppendingPathComponent:@"input.txt"]; FILE *cf = fopen(cmds.fileSystemRepresentation, "w"); if (cf) fclose(cf);
          setenv("TOTK_INPUT_FILE", cmds.fileSystemRepresentation, 1); }   // echo "shot ~/Desktop/shot.png" >> it

        NSString *log = [logs stringByAppendingPathComponent:@"by3.log"], *prev = [logs stringByAppendingPathComponent:@"by3.previous.log"];
        [NSFileManager.defaultManager removeItemAtPath:prev error:nil]; [NSFileManager.defaultManager moveItemAtPath:log toPath:prev error:nil];
        FILE *lf = fopen(log.fileSystemRepresentation, "w"); if (lf) { dup2(fileno(lf), STDOUT_FILENO); dup2(fileno(lf), STDERR_FILENO); fclose(lf); }
        fprintf(stderr, "[launcher] work %s, patches %s, present %s Hz, fullscreen %s, window %s\n", work.UTF8String, getenv("BY3_PATCHES"),
                getenv("DM_PRESENT_HZ"), getenv("BY3_FULLSCREEN") ? "yes" : "no", getenv("TOTK_WINDOW_SIZE"));
        NSString *binary = [work stringByAppendingPathComponent:@"build/by3-native"];
        char *const args[] = {(char *)binary.fileSystemRepresentation, "rewritten/v120", "boot", NULL};
        execv(args[0], args);
        fprintf(stderr, "[launcher] execv failed: %s\n", strerror(errno));
        fail([NSString stringWithFormat:T("No se pudo iniciar el juego. Mira %@.", "Starting the game failed. See %@."), log]);
        return 1;
    }
}
