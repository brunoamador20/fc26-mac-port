/* No game code, no windows. Exit on our own after the identity can be inspected. */
#import <Cocoa/Cocoa.h>
#include <mach/mach.h>
#include "../runtime/app_bootstrap.h"
static char constructor_input[4096], constructor_runtime[4096];
__attribute__((constructor)) static void observe_initial_environment(void) {
    snprintf(constructor_input, sizeof constructor_input, "%s", getenv("TOTK_INPUT_FILE") ?: "");
    snprintf(constructor_runtime, sizeof constructor_runtime, "%s", getenv("FC26_RUNTIME_EXECUTABLE") ?: "");
}
int main(int argc, char **argv) {
    @autoreleasepool {
        if (fc26_apply_app_bootstrap()) return 7;
        char cwd[4096]; if (!getcwd(cwd, sizeof cwd)) return 8;
        NSMutableArray *args = [NSMutableArray array];
        for (int i = 1; i < argc; ++i) [args addObject:@(argv[i])];
        NSMutableDictionary *environment = [NSMutableDictionary dictionary];
        for (char **e = *_NSGetEnviron(); *e; ++e) {
            NSString *entry = @(*e); NSRange equal = [entry rangeOfString:@"="];
            environment[[entry substringToIndex:equal.location]] = [entry substringFromIndex:equal.location + 1];
        }
        audit_token_t token; mach_msg_type_number_t count = TASK_AUDIT_TOKEN_COUNT;
        if (task_info(mach_task_self(), TASK_AUDIT_TOKEN, (task_info_t)&token, &count) != KERN_SUCCESS) return 10;
        NSDictionary *report = @{@"pid":@(getpid()), @"pidversion":@(token.val[7]), @"cwd":@(cwd), @"args":args,
            @"environment":environment, @"constructorInput":@(constructor_input), @"constructorRuntime":@(constructor_runtime)};
        NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingSortedKeys error:nil];
        if (![json writeToFile:@"mock-report.json" atomically:YES]) return 9;
        fprintf(stdout, "mock stdout\n"); fflush(stdout);
        fprintf(stderr, "mock stderr\n");
        [NSApplication sharedApplication];
        NSApp.activationPolicy = NSApplicationActivationPolicyProhibited;
        [NSTimer scheduledTimerWithTimeInterval:8 repeats:NO block:^(NSTimer *timer) { (void)timer; [NSApp terminate:nil]; }];
        [NSApp run];
        return 0;
    }
}
