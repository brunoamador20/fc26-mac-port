/* Explicit real-game probe. Never opens settings or writes the player's preferences.
   Run under lockf -k /tmp/fc26-boot.lock with a disposable home containing a copied profile. */
#define main launcher_main
#include "../app/launcher.m"
#undef main
int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 3) return 2;
        NSUserDefaults *d = [[NSUserDefaults alloc] initWithSuiteName:@"org.macnativegames.fc26.real-test"];
        [d setVolatileDomain:@{@"fullscreen":@NO, @"size":@0, @"FPS60":@NO, @"metalfx":@NO, @"hud":@YES} forName:NSArgumentDomain];
        LaunchPlan *p = launch_plan(d, @(argv[1]), @(argv[2]), NSScreen.screens, NSScreen.mainScreen);
        p.slot = [@(argv[2]) stringByAppendingPathComponent:@"game-slot"];
        p.set[@"TOTK_GAME_SLOT_DIR"] = p.slot;
        p.set[@"TOTK_SLOT_OWNER"] = @"agent";
        p.set[@"TOTK_SLOT_PURPOSE"] = @"review-window-test";
        NSError *error = nil;
        if (!open_game(p, &error)) { fprintf(stderr, "%s\n", error.description.UTF8String); return 1; }
        return 0;
    }
}
