#import <UIKit/UIKit.h>
#import <AVFAudio/AVFAudio.h>
#import <QuartzCore/CAMetalLayer.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <math.h>
#include "runtime.h"

int totk_host_main(int argc, char **argv);
void runtime_ios_attach_layer(CAMetalLayer *layer, UIView *host);
static char *host_argv[3];
static void *run_host(void *unused) { (void)unused; return (void *)(intptr_t)totk_host_main(3, host_argv); }
/* The desktop keyboard-overlay shortcut has no counterpart on iOS. */
void runtime_shortcut_help_toggle(void) {}

@interface TOTKMetalView : UIView @end
@implementation TOTKMetalView
+ (Class)layerClass { return CAMetalLayer.class; }
@end

@interface TOTKTouchPad : UIView
@property(nonatomic,strong) NSMapTable<UITouch *, NSValue *> *points;
@property(nonatomic,strong) NSMapTable<UITouch *, NSValue *> *origins;   // where each camera-stick touch went down
@end
@implementation TOTKTouchPad
- (instancetype)initWithFrame:(CGRect)frame { if ((self=[super initWithFrame:frame])) { self.multipleTouchEnabled=YES; self.backgroundColor=UIColor.clearColor; self.points=[NSMapTable strongToStrongObjectsMapTable]; self.origins=[NSMapTable strongToStrongObjectsMapTable]; } return self; }
/* The buttons, as fractions of the view; a touch on the right side that misses them drives the camera (right stick). */
static const struct {CGFloat x,y;uint64_t bit;NSString *label;} kButtons[]={{.86,.69,1,@"A"},{.78,.78,2,@"B"},{.78,.60,4,@"X"},{.70,.69,8,@"Y"},{.70,.17,64,@"L"},{.86,.17,128,@"R"},{.50,.15,1024,@"+"},{.40,.15,2048,@"−"}};
static const unsigned kButtonCount=sizeof(kButtons)/sizeof(*kButtons);
- (uint64_t)buttonAt:(CGPoint)p {
    CGFloat w=self.bounds.size.width,h=self.bounds.size.height;uint64_t bits=0;
    for(unsigned i=0;i<kButtonCount;i++) if(hypot(p.x-w*kButtons[i].x,p.y-h*kButtons[i].y)<MAX(30,h*.075)) bits|=kButtons[i].bit;
    return bits;
}
- (CGFloat)stickRadius { return MIN(78,self.bounds.size.height*.16); }
static void stick_axes(CGPoint from,CGPoint to,CGFloat radius,int32_t *x,int32_t *y) {
    CGFloat dx=to.x-from.x,dy=from.y-to.y,dist=hypot(dx,dy);
    if (dist>radius) { dx*=radius/dist;dy*=radius/dist; }
    *x=(int32_t)(dx/radius*32767);*y=(int32_t)(dy/radius*32767);
}
- (void)updateState {
    RuntimeGamepadState s={.connected=1}; CGPoint center=CGPointMake(self.bounds.size.width*.18,self.bounds.size.height*.70); CGFloat radius=[self stickRadius];
    for (UITouch *t in self.points.keyEnumerator) {
        CGPoint p=[self.points objectForKey:t].CGPointValue; NSValue *origin=[self.origins objectForKey:t];
        if (origin) { stick_axes(origin.CGPointValue,p,radius,&s.rx,&s.ry);continue; }
        if (p.x<self.bounds.size.width*.38 && p.y>self.bounds.size.height*.38) { stick_axes(center,p,radius,&s.lx,&s.ly);continue; }
        s.buttons|=[self buttonAt:p];
    }
    runtime_touch_pad_set(&s);[self setNeedsDisplay];
}
- (void)touchesBegan:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event {
    (void)event;
    for(UITouch *t in touches){
        CGPoint p=[t locationInView:self];[self.points setObject:[NSValue valueWithCGPoint:p] forKey:t];
        if (p.x>=self.bounds.size.width*.5 && ![self buttonAt:p]) [self.origins setObject:[NSValue valueWithCGPoint:p] forKey:t];
    }
    [self updateState];
}
- (void)touchesMoved:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { (void)event;for(UITouch *t in touches)[self.points setObject:[NSValue valueWithCGPoint:[t locationInView:self]] forKey:t];[self updateState]; }
- (void)touchesEnded:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { (void)event;for(UITouch *t in touches){[self.points removeObjectForKey:t];[self.origins removeObjectForKey:t];}[self updateState]; }
- (void)touchesCancelled:(NSSet<UITouch *> *)touches withEvent:(UIEvent *)event { [self touchesEnded:touches withEvent:event]; }
- (void)drawRect:(CGRect)rect {
    (void)rect;CGContextRef c=UIGraphicsGetCurrentContext();UIColor *ink=[UIColor colorWithWhite:1 alpha:.32];CGContextSetStrokeColorWithColor(c,ink.CGColor);CGContextSetFillColorWithColor(c,[UIColor colorWithWhite:1 alpha:.09].CGColor);CGContextSetLineWidth(c,2);
    CGFloat w=self.bounds.size.width,h=self.bounds.size.height,r=[self stickRadius];CGPoint center=CGPointMake(w*.18,h*.70);CGContextStrokeEllipseInRect(c,CGRectMake(center.x-r,center.y-r,2*r,2*r));
    for (UITouch *t in self.origins.keyEnumerator) {   // the camera stick, drawn where the finger went down
        CGPoint o=[self.origins objectForKey:t].CGPointValue,p=[self.points objectForKey:t].CGPointValue;int32_t x,y;stick_axes(o,p,r,&x,&y);
        CGContextStrokeEllipseInRect(c,CGRectMake(o.x-r,o.y-r,2*r,2*r));
        CGPoint k=CGPointMake(o.x+x/32767.0*r,o.y-y/32767.0*r);CGRect knob=CGRectMake(k.x-23,k.y-23,46,46);CGContextFillEllipseInRect(c,knob);CGContextStrokeEllipseInRect(c,knob);
    }
    NSDictionary *attrs=@{NSFontAttributeName:[UIFont systemFontOfSize:17 weight:UIFontWeightSemibold],NSForegroundColorAttributeName:ink};
    for(unsigned i=0;i<kButtonCount;i++){CGPoint p=CGPointMake(w*kButtons[i].x,h*kButtons[i].y);CGRect box=CGRectMake(p.x-23,p.y-23,46,46);CGContextFillEllipseInRect(c,box);CGContextStrokeEllipseInRect(c,box);CGSize z=[kButtons[i].label sizeWithAttributes:attrs];[kButtons[i].label drawAtPoint:CGPointMake(p.x-z.width/2,p.y-z.height/2) withAttributes:attrs];}
}
@end

@interface TOTKGameController : UIViewController @property(nonatomic,strong) TOTKMetalView *gameView; @end
@implementation TOTKGameController
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    self.gameView = [[TOTKMetalView alloc] initWithFrame:self.view.bounds];
    self.gameView.autoresizingMask = UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;
    [self.view addSubview:self.gameView];
    runtime_ios_attach_layer((CAMetalLayer *)self.gameView.layer, self.gameView);
    TOTKTouchPad *pad=[[TOTKTouchPad alloc] initWithFrame:self.view.bounds];pad.autoresizingMask=UIViewAutoresizingFlexibleWidth|UIViewAutoresizingFlexibleHeight;[self.view addSubview:pad];
}
- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    static BOOL started; if (started) return; started = YES;
    pthread_attr_t attr; pthread_attr_init(&attr); pthread_attr_setstacksize(&attr, 64u << 20);
    pthread_t thread; pthread_create(&thread, &attr, run_host, NULL);
    pthread_detach(thread); pthread_attr_destroy(&attr);
}
- (BOOL)prefersHomeIndicatorAutoHidden { return YES; }
- (BOOL)prefersStatusBarHidden { return YES; }
- (UIInterfaceOrientationMask)supportedInterfaceOrientations { return UIInterfaceOrientationMaskLandscape; }
@end

@interface TOTKApp : UIResponder <UIApplicationDelegate> @property(nonatomic,strong) UIWindow *window; @end
@implementation TOTKApp
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)options;
    // Controller input does not reset the idle timer; auto-lock would suspend the game mid-play or mid shader import.
    application.idleTimerDisabled = YES;
    NSFileManager *fm = NSFileManager.defaultManager;
    NSString *docs = NSSearchPathForDirectoriesInDomains(NSDocumentDirectory,NSUserDomainMask,YES).firstObject;
    NSString *res = [NSBundle.mainBundle.resourcePath stringByAppendingPathComponent:@"GameData"];
    for (NSString *name in @[@"save", @"temp", @"shader-cache", @"game-slot"]) [fm createDirectoryAtPath:[docs stringByAppendingPathComponent:name] withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *log = [docs stringByAppendingPathComponent:@"log.txt"];
    if (freopen(log.fileSystemRepresentation,"w",stderr)) setvbuf(stderr,NULL,_IOLBF,0);
    setenv("TOTK_ROMFS",[res stringByAppendingPathComponent:@"romfs"].fileSystemRepresentation,1);
    setenv("TOTK_OPERATION_MODE","handheld",1);
    setenv("TOTK_ROMFS_PATCHES",[res stringByAppendingPathComponent:@"romfs-patches"].fileSystemRepresentation,1);
    setenv("TOTK_ROMFS_PATCHES_OUT",[res stringByAppendingPathComponent:@"romfs-patches-out"].fileSystemRepresentation,1);
    setenv("TOTK_SHARED_FONTS",[res stringByAppendingPathComponent:@"shared-fonts"].fileSystemRepresentation,1);
    setenv("TOTK_SHADER_SEED_DIR",[res stringByAppendingPathComponent:@"shader-seed"].fileSystemRepresentation,1);
    setenv("TOTK_SHADER_CACHE",[docs stringByAppendingPathComponent:@"shader-cache"].fileSystemRepresentation,1);
    setenv("DM_NVN_SHMAP",[res stringByAppendingPathComponent:@"shader-seed/shader_map.tsv"].fileSystemRepresentation,1);
    setenv("DM_MSL_DIR",[res stringByAppendingPathComponent:@"shader-seed"].fileSystemRepresentation,1);
    NSString *font = [res stringByAppendingPathComponent:@"font"]; setenv("TOTK_FONT_DIR",font.fileSystemRepresentation,1);
    // Same player environment as the Mac launcher (app/launcher.m); the bundle is read-only, so state goes to Documents.
    setenv("TOTK_PROFILE_DIR",[docs stringByAppendingPathComponent:@"save"].fileSystemRepresentation,1);
    setenv("TOTK_GAME_SLOT_DIR",[docs stringByAppendingPathComponent:@"game-slot"].fileSystemRepresentation,1);
    setenv("TOTK_ROMFS_PROOF_DIR",docs.fileSystemRepresentation,1);   // hash the 17 GB RomFS once, not on every launch
    for (NSString *name in @[@"TOTK_GPU_ALLOW_SUBMIT",@"TOTK_GPU_WIDEN",@"TOTK_GPU_BLOCKRT",@"TOTK_GPU_MIDCLEAR"]) setenv(name.UTF8String,"1",1);
    setenv("TOTK_SLOT_OWNER","user",0); setenv("TOTK_SLOT_PURPOSE","player",0);
    unsetenv("TOTK_AUTOLOAD");
    chdir(docs.fileSystemRepresentation);
    host_argv[0] = strdup("TOTK"); host_argv[1] = strdup(res.fileSystemRepresentation); host_argv[2] = strdup("boot");
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [TOTKGameController new]; [self.window makeKeyAndVisible]; return YES;
}
@end

int main(int argc, char **argv) { @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(TOTKApp.class)); } }
