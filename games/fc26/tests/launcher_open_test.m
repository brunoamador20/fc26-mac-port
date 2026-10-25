/* Explicit, windowless end-to-end probe; not run during unittest discovery. */
#define main launcher_main
#include "../app/launcher.m"
#undef main
int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc != 3) return 2;
        NSUserDefaults *d = [[NSUserDefaults alloc] initWithSuiteName:@"org.macnativegames.fc26.open-test"];
        LaunchPlan *p = launch_plan(d, @(argv[1]), @(argv[2]), @[], nil);
        NSDictionary *expected = game_environment(p, inherited_environment());
        NSData *json = [NSJSONSerialization dataWithJSONObject:expected options:NSJSONWritingSortedKeys error:nil];
        if (![json writeToFile:[p.work stringByAppendingPathComponent:@"mock-expected.json"] atomically:YES]) return 3;
        NSError *error = nil;
        if (!open_game(p, &error)) { fprintf(stderr, "%s\n", error.description.UTF8String); return 1; }
        return 0;
    }
}
