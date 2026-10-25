#define main launcher_main
#include "../app/launcher.m"
#undef main
int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 3 && argc != 4) return 2;
        NSUserDefaults *d = [[NSUserDefaults alloc] initWithSuiteName:@"org.macnativegames.fc26.app-test"];
        [d registerDefaults:@{@"FPS60": @(argc == 4 && !strcmp(argv[3], "1"))}];
        LaunchPlan *p = launch_plan(d, @(argv[1]), @(argv[2]), @[], nil);
        NSError *error = nil;
        NSURL *url = prepare_game_app(p, &error);
        if (!url) { fprintf(stderr, "%s\n", error.description.UTF8String); return 1; }
        NSDictionary *env = game_environment(p, @{@"KEEP": @"ok", @"FC26_AUDIO": @"0", @"TOTK_HEADLESS": @"1", @"FC26_FPS60": @"inherited"});
        if (env[@"FC26_AUDIO"] || env[@"TOTK_HEADLESS"] || ![env[@"KEEP"] isEqual:@"ok"]) return 3;
        NSData *json = [NSJSONSerialization dataWithJSONObject:@{@"app":url.path, @"environment":env} options:0 error:nil];
        fwrite(json.bytes, 1, json.length, stdout);
        return 0;
    }
}
