#import <Foundation/Foundation.h>
#import <CoreLocation/CoreLocation.h>
#import <UserNotifications/UserNotifications.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <os/log.h>

typedef BOOL (*ShundoBoolGetter)(id, SEL);
typedef id (*ShundoObjectGetter)(id, SEL);

static ShundoBoolGetter ShundoOriginalSimulatedGetter = NULL;
static ShundoObjectGetter ShundoOriginalSourceInformationGetter = NULL;
static NSUInteger ShundoSourceInformationCallCount = 0;

static BOOL ShundoReturnFalse(id object, SEL selector) {
    return NO;
}

static id ShundoSourceInformation(id location, SEL selector) {
    id sourceInformation = ShundoOriginalSourceInformationGetter != NULL
        ? ShundoOriginalSourceInformationGetter(location, selector)
        : nil;
    BOOL originalSimulated = NO;
    BOOL exposedSimulated = NO;
    SEL simulatedSelector = NSSelectorFromString(@"isSimulatedBySoftware");
    if (sourceInformation != nil) {
        if (ShundoOriginalSimulatedGetter != NULL) {
            originalSimulated = ShundoOriginalSimulatedGetter(sourceInformation, simulatedSelector);
        }
        if ([sourceInformation respondsToSelector:simulatedSelector]) {
            exposedSimulated = ((ShundoBoolGetter)objc_msgSend)(sourceInformation, simulatedSelector);
        }
    }
    ShundoSourceInformationCallCount += 1;
    if (ShundoSourceInformationCallCount <= 12 || ShundoSourceInformationCallCount % 100 == 0) {
        os_log_with_type(
            OS_LOG_DEFAULT,
            OS_LOG_TYPE_DEFAULT,
            "SHUNDO_LOCATION_SOURCE call=%{public}lu present=%{public}d originalSimulated=%{public}d exposedSimulated=%{public}d",
            (unsigned long)ShundoSourceInformationCallCount,
            sourceInformation != nil,
            originalSimulated,
            exposedSimulated
        );
    }
    return sourceInformation;
}

static BOOL ShundoInstallLocationMask(void) {
    Class sourceInformationClass = NSClassFromString(@"CLLocationSourceInformation");
    SEL simulatedSelector = NSSelectorFromString(@"isSimulatedBySoftware");
    Method simulatedMethod = class_getInstanceMethod(sourceInformationClass, simulatedSelector);
    if (simulatedMethod == NULL) {
        os_log_with_type(OS_LOG_DEFAULT, OS_LOG_TYPE_ERROR, "SHUNDO_LOCATION_MASK_FAILED stage=simulated-method");
        return NO;
    }
    ShundoOriginalSimulatedGetter = (ShundoBoolGetter)method_setImplementation(
        simulatedMethod,
        (IMP)ShundoReturnFalse
    );

    Method sourceInformationMethod = class_getInstanceMethod(
        [CLLocation class],
        NSSelectorFromString(@"sourceInformation")
    );
    if (sourceInformationMethod == NULL) {
        os_log_with_type(OS_LOG_DEFAULT, OS_LOG_TYPE_ERROR, "SHUNDO_LOCATION_MASK_FAILED stage=source-method");
        return NO;
    }
    ShundoOriginalSourceInformationGetter = (ShundoObjectGetter)method_setImplementation(
        sourceInformationMethod,
        (IMP)ShundoSourceInformation
    );
    os_log_with_type(OS_LOG_DEFAULT, OS_LOG_TYPE_DEFAULT, "SHUNDO_LOCATION_MASK_READY");
    return YES;
}

@interface UNUserNotificationCenter (ShundoNotificationBridge)
- (void)shundo_addNotificationRequest:(UNNotificationRequest *)request
                withCompletionHandler:(void (^)(NSError *error))completionHandler;
@end

@implementation UNUserNotificationCenter (ShundoNotificationBridge)

- (void)shundo_addNotificationRequest:(UNNotificationRequest *)request
                withCompletionHandler:(void (^)(NSError *error))completionHandler {
    UNNotificationContent *content = request.content;
    NSString *title = content.title ?: @"";
    NSString *subtitle = content.subtitle ?: @"";
    NSString *body = content.body ?: @"";
    NSString *identifier = request.identifier ?: @"";

    os_log_with_type(
        OS_LOG_DEFAULT,
        OS_LOG_TYPE_DEFAULT,
        "SHUNDO_HUNTER_NOTIFICATION id=%{public}@ title=%{public}@ subtitle=%{public}@ body=%{public}@",
        identifier,
        title,
        subtitle,
        body
    );

    [self shundo_addNotificationRequest:request withCompletionHandler:completionHandler];
}

@end

__attribute__((constructor))
static void ShundoInstallNotificationBridge(void) {
    BOOL locationMaskReady = ShundoInstallLocationMask();
    Class notificationCenter = NSClassFromString(@"UNUserNotificationCenter");
    Method original = class_getInstanceMethod(
        notificationCenter,
        @selector(addNotificationRequest:withCompletionHandler:)
    );
    Method replacement = class_getInstanceMethod(
        notificationCenter,
        @selector(shundo_addNotificationRequest:withCompletionHandler:)
    );
    if (original != NULL && replacement != NULL) {
        method_exchangeImplementations(original, replacement);
        os_log_with_type(
            OS_LOG_DEFAULT,
            OS_LOG_TYPE_DEFAULT,
            "SHUNDO_HUNTER_BRIDGE_READY locationMask=%{public}d",
            locationMaskReady
        );
    } else {
        os_log_with_type(OS_LOG_DEFAULT, OS_LOG_TYPE_ERROR, "SHUNDO_HUNTER_BRIDGE_FAILED");
    }
}
