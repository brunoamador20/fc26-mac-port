/* Read the bottom-right HUD clock from a displayed 16:9 game screenshot.
   A tight, enlarged crop also works with a 720p diagnostic window and a bright
   scene; the original broad ROI missed small clock text against blue effects. */
#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
#import <ImageIO/ImageIO.h>
#include <stdio.h>

int main(int argc, char **argv) { @autoreleasepool {
    if (argc != 2) { fprintf(stderr, "usage: read-game-clock <png>\n"); return 2; }
    NSURL *url = [NSURL fileURLWithPath:@(argv[1])];
    CGImageSourceRef src = CGImageSourceCreateWithURL((__bridge CFURLRef)url, NULL);
    if (!src) return 2;
    CGImageRef image = CGImageSourceCreateImageAtIndex(src, 0, NULL); CFRelease(src);
    if (!image) return 2;
    size_t width=CGImageGetWidth(image),height=CGImageGetHeight(image);
    CGImageRef crop=CGImageCreateWithImageInRect(image,CGRectMake(width*.72,height*.865,width*.10,height*.055));
    CGImageRelease(image);if(!crop)return 2;
    size_t cw=CGImageGetWidth(crop)*4,ch=CGImageGetHeight(crop)*4;
    CGColorSpaceRef space=CGColorSpaceCreateDeviceRGB();
    CGContextRef context=CGBitmapContextCreate(NULL,cw,ch,8,cw*4,space,(CGBitmapInfo)kCGImageAlphaPremultipliedLast);
    CGColorSpaceRelease(space);if(!context){CGImageRelease(crop);return 2;}
    CGContextSetInterpolationQuality(context,kCGInterpolationHigh);
    CGContextDrawImage(context,CGRectMake(0,0,cw,ch),crop);CGImageRelease(crop);
    image=CGBitmapContextCreateImage(context);CGContextRelease(context);
    if(!image)return 2;
    VNRecognizeTextRequest *request = [VNRecognizeTextRequest new];
    request.recognitionLevel = VNRequestTextRecognitionLevelAccurate;
    request.usesLanguageCorrection = NO;
    request.recognitionLanguages = @[@"en-US"];
    request.minimumTextHeight = .02;
    VNImageRequestHandler *handler = [[VNImageRequestHandler alloc] initWithCGImage:image options:@{}];
    NSError *error = nil;
    BOOL ok = [handler performRequests:@[request] error:&error]; CGImageRelease(image);
    if (!ok) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
    for (VNRecognizedTextObservation *result in request.results)
        for (VNRecognizedText *candidate in [result topCandidates:3])
            printf("%s\t%.3f\n", candidate.string.UTF8String, candidate.confidence);
    return 0;
} }
