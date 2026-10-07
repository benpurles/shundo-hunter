/**
 * Copyright (c) 2015-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the BSD-style license found in the
 * LICENSE file in the root directory of this source tree.
 */

#import "FBDebugCommands.h"

#import "FBRouteRequest.h"
#import "FBSession.h"
#import "FBXMLGenerationOptions.h"
#import "XCUIApplication+FBHelpers.h"
#import "XCUIElement+FBUtilities.h"
#import "XCUIApplication+FBQuiescence.h"
#import "FBXCElementSnapshotWrapper.h"
#import "XCUIElement+FBWebDriverAttributes.h"
#import "XCUIDevice+FBHelpers.h"
#import "FBXPath.h"

@implementation FBDebugCommands

#pragma mark - <FBCommandHandler>

+ (NSArray *)routes
{
  return
  @[
    [[FBRoute GET:@"/source"] respondWithTarget:self action:@selector(handleGetSourceCommand:)],
    [[FBRoute GET:@"/source"].withoutSession respondWithTarget:self action:@selector(handleGetSourceCommand:)],
    [[FBRoute GET:@"/wda/hunter/notifications"].withoutSession respondWithTarget:self action:@selector(handleHunterNotifications:)],
    [[FBRoute GET:@"/wda/accessibleSource"] respondWithTarget:self action:@selector(handleGetAccessibleSourceCommand:)],
    [[FBRoute GET:@"/wda/accessibleSource"].withoutSession respondWithTarget:self action:@selector(handleGetAccessibleSourceCommand:)],
  ];
}


#pragma mark - Commands

// Hunter's read-only phone-side bridge. Never activate apps, open Notification
// Center, tap, or return other apps' notification content. The Mac display is
// not involved. Keep the response restricted to a visible, compact top banner
// containing both the exact game app label and its Hundo/Shundo message.
+ (void)hunterTexts:(NSDictionary *)node into:(NSMutableOrderedSet *)texts
{
  for (NSString *key in @[@"label", @"value", @"name"]) {
    id value = node[key];
    if ([value isKindOfClass:NSString.class] && [value length] > 0) {
      [texts addObject:value];
    }
  }
  for (NSDictionary *child in node[@"children"] ?: @[]) {
    [self hunterTexts:child into:texts];
  }
}

+ (void)hunterBanners:(NSDictionary *)node into:(NSMutableArray *)banners screenHeight:(CGFloat)height
{
  NSUInteger before = banners.count;
  for (NSDictionary *child in node[@"children"] ?: @[]) {
    [self hunterBanners:child into:banners screenHeight:height];
  }
  if (banners.count > before) { return; } // Only the smallest matching subtree.
  NSDictionary *rect = node[@"rect"];
  CGFloat y = [rect[@"y"] doubleValue], h = [rect[@"height"] doubleValue];
  CGFloat w = [rect[@"width"] doubleValue];
  if (h < 25 || h > height * .36 || y < 0 || y > height * .22 || w < 180) { return; }
  // wd tree stores computed visibility as isVisible (string 0/1).
  if (![node[@"isVisible"] boolValue]) { return; }
  NSMutableOrderedSet *texts = [NSMutableOrderedSet orderedSet];
  [self hunterTexts:node into:texts];
  BOOL source = NO;
  for (NSString *text in texts) {
    NSString *folded = [[text stringByFoldingWithOptions:NSDiacriticInsensitiveSearch locale:nil] lowercaseString];
    if ([folded isEqualToString:@"pokemon go"] || [folded isEqualToString:@"ipogo"]) { source = YES; }
  }
  NSString *body = [[texts array] componentsJoinedByString:@" · "];
  NSRegularExpression *pattern = [NSRegularExpression regularExpressionWithPattern:@"\\b(?:shundo|hundo)\\b" options:NSRegularExpressionCaseInsensitive error:nil];
  if (source && [pattern firstMatchInString:body options:0 range:NSMakeRange(0, body.length)] && body.length <= 2000) {
    [banners addObject:@{@"sourceBundleId": @"com.nianticlabs.pokemongo", @"text": body, @"rect": rect}];
  }
}

+ (id<FBResponsePayload>)handleHunterNotifications:(FBRouteRequest *)request
{
  XCUIApplication *springboard = [[XCUIApplication alloc] initWithBundleIdentifier:@"com.apple.springboard"];
  springboard.fb_shouldWaitForQuiescence = NO;
  id<FBXCElementSnapshot> snapshot = [springboard fb_standardSnapshot];
  if (!snapshot) { return FBResponseWithUnknownErrorFormat(@"Phone notification snapshot unavailable"); }
  NSMutableArray *banners = [NSMutableArray array];
  [self hunterSnapshot:snapshot into:banners screenHeight:CGRectGetHeight(snapshot.frame)];
  // Active app metadata is used only for the game/lock guard; no other app
  // names, labels, or notification text leave the phone.
  BOOL gameActive = NO;
  for (NSDictionary *app in XCUIApplication.fb_activeAppsInfo) {
    if ([app[@"bundleId"] isEqual:@"com.nianticlabs.pokemongo"]) { gameActive = YES; }
  }
  return FBResponseWithObject(@{@"protocol": @1, @"readerRevision": @2, @"source": @"iphone-banner", @"gameActive": @(gameActive), @"screenLocked": @([[XCUIDevice sharedDevice] fb_isScreenLocked]), @"banners": banners});
}

+ (NSDictionary *)hunterCompactTree:(id<FBXCElementSnapshot>)snapshot
{
  NSMutableArray *children = [NSMutableArray array];
  for (id<FBXCElementSnapshot> child in snapshot.children) {
    [children addObject:[self hunterCompactTree:child]];
  }
  CGRect f = snapshot.frame;
  // Labels and frame come from the single snapshot. Do not request expensive
  // custom visibility/actions/traits for every hidden SpringBoard element.
  return @{@"label": snapshot.label ?: @"", @"value": snapshot.value ?: @"",
           @"name": snapshot.identifier ?: @"", @"children": children,
           @"rect": @{@"x": @(f.origin.x), @"y": @(f.origin.y),
                      @"width": @(f.size.width), @"height": @(f.size.height)}};
}

+ (void)hunterSnapshot:(id<FBXCElementSnapshot>)snapshot into:(NSMutableArray *)banners screenHeight:(CGFloat)height
{
  if ([snapshot.identifier isEqualToString:@"NotificationShortLookView"]) {
    CGRect frame = snapshot.frame;
    if (frame.origin.y < 0 || frame.origin.y > height * .22 || frame.size.height < 25 || frame.size.height > height * .36) { return; }
    FBXCElementSnapshotWrapper *wrapper = [FBXCElementSnapshotWrapper ensureWrapped:snapshot];
    if (![wrapper isWDVisible]) { return; }
    NSMutableDictionary *tree = [[self hunterCompactTree:snapshot] mutableCopy];
    tree[@"isVisible"] = @YES;
    [self hunterBanners:tree into:banners screenHeight:height];
    return;
  }
  for (id<FBXCElementSnapshot> child in snapshot.children) {
    [self hunterSnapshot:child into:banners screenHeight:height];
  }
}

static NSString *const SOURCE_FORMAT_XML = @"xml";
static NSString *const SOURCE_FORMAT_JSON = @"json";
static NSString *const SOURCE_FORMAT_DESCRIPTION = @"description";

+ (id<FBResponsePayload>)handleGetSourceCommand:(FBRouteRequest *)request
{
  // This method might be called without session
  XCUIApplication *application = request.session.activeApplication ?: XCUIApplication.fb_activeApplication;
  NSString *sourceType = request.parameters[@"format"] ?: SOURCE_FORMAT_XML;
  NSString *sourceScope = request.parameters[@"scope"];
  id result;
  if ([sourceType caseInsensitiveCompare:SOURCE_FORMAT_XML] == NSOrderedSame) {
    NSArray<NSString *> *excludedAttributes = nil == request.parameters[@"excluded_attributes"]
      ? nil
      : [request.parameters[@"excluded_attributes"] componentsSeparatedByString:@","];
    result = [application fb_xmlRepresentationWithOptions:
        [[[FBXMLGenerationOptions new]
          withExcludedAttributes:excludedAttributes]
         withScope:sourceScope]];
  } else if ([sourceType caseInsensitiveCompare:SOURCE_FORMAT_JSON] == NSOrderedSame) {
    NSString *excludedAttributesString = request.parameters[@"excluded_attributes"];
    NSSet<NSString *> *excludedAttributes = (excludedAttributesString == nil)
          ? nil
          : [NSSet setWithArray:[excludedAttributesString componentsSeparatedByString:@","]];

    result = [application fb_tree:excludedAttributes];
  } else if ([sourceType caseInsensitiveCompare:SOURCE_FORMAT_DESCRIPTION] == NSOrderedSame) {
    result = application.fb_descriptionRepresentation;
  } else {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:[NSString stringWithFormat:@"Unknown source format '%@'. Only %@ source formats are supported.",
                                                                                  sourceType, @[SOURCE_FORMAT_XML, SOURCE_FORMAT_JSON, SOURCE_FORMAT_DESCRIPTION]] traceback:nil]);
  }
  if (nil == result) {
    return FBResponseWithUnknownErrorFormat(@"Cannot get '%@' source of the current application", sourceType);
  }
  return FBResponseWithObject(result);
}

+ (id<FBResponsePayload>)handleGetAccessibleSourceCommand:(FBRouteRequest *)request
{
  // This method might be called without session
  XCUIApplication *application = request.session.activeApplication ?: XCUIApplication.fb_activeApplication;
  return FBResponseWithObject(application.fb_accessibilityTree ?: @{});
}

@end
