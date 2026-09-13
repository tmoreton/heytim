import XCTest

@MainActor final class FroggyBotAppleUITests: XCTestCase {
  func testNativeSignInMatchesTheFroggyBotFlow() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing-auth"]
    app.launch()

    XCTAssertTrue(app.staticTexts["FroggyBot"].firstMatch.waitForExistence(timeout: 10))
    XCTAssertTrue(app.staticTexts["Welcome back"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.textFields["Email address"].exists)
    XCTAssertTrue(app.buttons["Continue"].exists)
    XCTAssertTrue(app.descendants(matching: .any)["Need an invite? Request beta access"].exists)
  }

  func testNativeConversationLaunchesAndSendsAMessage() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    // A vertically growing SwiftUI TextField is exposed as a TextField on some
    // iOS releases and as a TextView on others, so match its accessible label.
    let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
    XCTAssertTrue(composer.waitForExistence(timeout: 10))

    #if os(iOS)
      let details = app.buttons["chat.details"]
      XCTAssertTrue(details.waitForExistence(timeout: 5))
      let chiefTitles = app.staticTexts.matching(identifier: "Chief").allElementsBoundByIndex
      XCTAssertFalse(chiefTitles.isEmpty)
      XCTAssertTrue(
        chiefTitles.allSatisfy { $0.frame.isEmpty || $0.frame.maxY <= details.frame.maxY + 16 })
      app.buttons["FroggyBot"].tap()
    #endif
    XCTAssertTrue(app.searchFields["Search chats"].waitForExistence(timeout: 5))
    let chief = app.staticTexts["Chief"].firstMatch
    XCTAssertTrue(chief.waitForExistence(timeout: 5))
    chief.tap()
    XCTAssertTrue(composer.waitForExistence(timeout: 5))

    composer.tap()
    composer.typeText("Native smoke test")
    #if os(iOS)
      XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 2))
      app.scrollViews["chat.transcript"].tap()
      XCTAssertFalse(app.keyboards.firstMatch.waitForExistence(timeout: 1))
      composer.tap()
    #endif
    app.buttons["chat.send"].tap()
    XCTAssertTrue(
      app.staticTexts["This is the native app’s offline test reply."].waitForExistence(timeout: 5))
    XCTAssertFalse(app.buttons["Jump to Latest"].exists)
  }

  func testEmptyConversationIsCenteredInTheAvailableSpace() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-empty-conversation"]
    app.launch()

    let emptyTitle = app.staticTexts["Start a conversation"]
    let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
    let details = app.buttons["chat.details"]
    XCTAssertTrue(emptyTitle.waitForExistence(timeout: 10))
    XCTAssertTrue(composer.waitForExistence(timeout: 5))
    XCTAssertTrue(details.waitForExistence(timeout: 5))

    #if os(iOS)
      let availableMidY = (details.frame.maxY + composer.frame.minY) / 2
      XCTAssertLessThan(abs(emptyTitle.frame.midY - availableMidY), 90)
    #endif
  }

  func testActivityIsFormattedAndInitiallyFollowsTheLatestUpdate() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-activity"]
    app.launch()

    let latestStep = app.descendants(matching: .any)["chat.activity.step.9"].firstMatch
    let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
    XCTAssertTrue(latestStep.waitForExistence(timeout: 10))
    XCTAssertTrue(composer.waitForExistence(timeout: 5))
    XCTAssertTrue(latestStep.isHittable)
    XCTAssertTrue(composer.isHittable)
    XCTAssertFalse(app.staticTexts["Checking `README.md` for the intended release workflow."].exists)
  }

  func testGroupProgressUsesCompactStatusRowsWithoutEmptyReplyBubbles() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-group-progress"]
    app.launch()

    let running = app.descendants(matching: .any)["chat.progress.running"].firstMatch
    let queued = app.descendants(matching: .any)["chat.progress.pending"].firstMatch
    let waiting = app.descendants(matching: .any)["chat.progress.waiting"].firstMatch
    XCTAssertTrue(running.waitForExistence(timeout: 10))
    XCTAssertTrue(queued.waitForExistence(timeout: 5))
    XCTAssertTrue(waiting.waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Working · 2 updates"].exists)
    XCTAssertTrue(app.staticTexts["Queued"].exists)
    XCTAssertTrue(app.staticTexts["Waiting for its turn"].exists)
    XCTAssertTrue(app.staticTexts["Who should answer?"].exists)
    XCTAssertFalse(app.staticTexts["Activity"].exists)
    XCTAssertFalse(app.staticTexts["Pending"].exists)
    XCTAssertFalse(app.descendants(matching: .any)["chat.message.content.group-running"].exists)
    XCTAssertFalse(app.descendants(matching: .any)["chat.message.content.group-pending"].exists)
    XCTAssertFalse(app.descendants(matching: .any)["chat.message.content.group-waiting"].exists)

    #if os(iOS)
      XCTAssertLessThan(running.frame.height, 180)
      XCTAssertLessThan(queued.frame.height, 80)
      XCTAssertLessThan(waiting.frame.height, 80)
    #else
      XCTAssertTrue(
        app.descendants(matching: .any)["sidebar.processing.group.research-team"]
          .waitForExistence(timeout: 5))
      XCTAssertTrue(app.staticTexts["Working"].exists)
      let replyPicker = app.descendants(matching: .any)["chat.replyPicker"]
      XCTAssertTrue(replyPicker.waitForExistence(timeout: 5))
      XCTAssertTrue(replyPicker.isHittable)
    #endif
  }

  func testMessageMarkdownUsesNativeBlockFormatting() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-markdown"]
    app.launch()

    XCTAssertTrue(app.staticTexts["Release check"].waitForExistence(timeout: 10))
    XCTAssertTrue(app.staticTexts["1."].exists)
    XCTAssertTrue(app.staticTexts["2."].exists)
    XCTAssertTrue(app.staticTexts["Item"].exists)
    XCTAssertTrue(app.staticTexts["Status"].exists)
    XCTAssertTrue(app.staticTexts["Credentials"].exists)
    XCTAssertTrue(app.staticTexts["Protected"].exists)
    XCTAssertFalse(app.staticTexts["## Release check"].exists)
    XCTAssertFalse(app.staticTexts["| Item | Status |"].exists)
  }

  func testComposerUsesNativeAttachmentMenu() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    let attachmentMenu = app.buttons["chat.attachments"]
    XCTAssertTrue(attachmentMenu.waitForExistence(timeout: 10))
    let microphone = app.buttons["chat.microphone"]
    XCTAssertTrue(microphone.waitForExistence(timeout: 5))
    XCTAssertTrue(microphone.isHittable)
    attachmentMenu.tap()

    XCTAssertTrue(app.buttons["Photo Library"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.buttons["Choose Files"].exists)
  }

  func testConversationDetailsUsesTheNativeInspector() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    let details = app.buttons["chat.details"]
    XCTAssertTrue(details.waitForExistence(timeout: 10))
    details.tap()

    #if os(iOS)
      XCTAssertTrue(app.navigationBars["Details"].waitForExistence(timeout: 5))
      XCTAssertTrue(app.buttons["Close"].exists)
      XCTAssertFalse(app.buttons["Done"].exists)
    #else
      XCTAssertTrue(app.staticTexts["Details"].waitForExistence(timeout: 5))
      XCTAssertFalse(app.buttons["Done"].exists)
    #endif
    XCTAssertTrue(app.buttons["Memory"].exists)
  }

  func testAccountSettingsUsesTheFroggyBotLayout() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    #if os(iOS)
      let sidebar = app.buttons["FroggyBot"]
      XCTAssertTrue(sidebar.waitForExistence(timeout: 10))
      sidebar.tap()
    #endif
    let create = app.buttons["sidebar.create"]
    XCTAssertTrue(create.waitForExistence(timeout: 10))
    XCTAssertTrue(create.isHittable)
    let settings = app.buttons["sidebar.settings"]
    XCTAssertTrue(settings.waitForExistence(timeout: 10))
    XCTAssertTrue(settings.isHittable)
    #if os(iOS)
      XCTAssertLessThan(settings.frame.maxX, create.frame.minX)
      XCTAssertEqual(settings.frame.midY, create.frame.midY, accuracy: 4)
    #endif
    settings.tap()

    XCTAssertTrue(app.staticTexts["Settings"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Memory"].exists)
    XCTAssertTrue(app.staticTexts["Add a Bot"].exists)
    XCTAssertTrue(app.staticTexts["Capabilities"].exists)
    XCTAssertTrue(app.staticTexts["Connected Accounts"].exists)
    #if os(iOS)
      XCTAssertTrue(app.buttons["Close"].exists)
      XCTAssertFalse(app.buttons["Done"].exists)
    #else
      XCTAssertTrue(app.sheets.firstMatch.waitForExistence(timeout: 5))
      XCTAssertTrue(app.buttons["Close"].exists)
      XCTAssertFalse(app.buttons["Done"].exists)
      XCTAssertEqual(app.windows.count, 1)
    #endif

    let exportMemory = app.buttons["Export Memory"]
    for _ in 0..<4 where !exportMemory.exists { app.swipeUp() }
    XCTAssertTrue(exportMemory.waitForExistence(timeout: 5))

    let aboutValue = app.staticTexts["App, FroggyBot for Apple"]
    for _ in 0..<4 where !aboutValue.exists { app.swipeUp() }
    XCTAssertTrue(aboutValue.waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Platforms, iPhone + Mac"].exists)
    XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Version,'")).firstMatch.exists)
  }

  func testAddBotGalleryExplainsTheConfiguredSkillsToolsAndPrompt() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    #if os(iOS)
      app.buttons["FroggyBot"].tap()
    #endif
    let create = app.buttons["sidebar.create"]
    XCTAssertTrue(create.waitForExistence(timeout: 10))
    XCTAssertFalse(app.buttons["sidebar.addBot"].exists)
    create.tap()
    let addBot = app.buttons["Add a bot"]
    XCTAssertTrue(addBot.waitForExistence(timeout: 5))
    addBot.tap()

    XCTAssertTrue(app.staticTexts["Add a Bot"].waitForExistence(timeout: 5))
    let template = app.buttons["bot.template.research-reports"]
    XCTAssertTrue(template.waitForExistence(timeout: 5))
    template.tap()

    XCTAssertTrue(
      app.descendants(matching: .any)["bot.template.skills"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Deep Research"].exists)
    XCTAssertTrue(app.descendants(matching: .any)["bot.template.tools"].exists)
    XCTAssertTrue(app.staticTexts["Web Search"].exists)
    XCTAssertTrue(app.staticTexts["Files & Data"].exists)
    XCTAssertTrue(app.buttons["View Full Instructions"].exists)
    XCTAssertTrue(app.buttons["Add Bot"].exists)
  }

  func testCapabilitiesShowsBothSkillsAndBuiltInTools() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launch()

    #if os(iOS)
      app.buttons["FroggyBot"].tap()
    #endif
    XCTAssertTrue(app.buttons["sidebar.settings"].waitForExistence(timeout: 10))
    app.buttons["sidebar.settings"].tap()
    XCTAssertTrue(app.staticTexts["Capabilities"].waitForExistence(timeout: 5))
    app.staticTexts["Capabilities"].tap()

    XCTAssertTrue(app.staticTexts["Deep Research"].waitForExistence(timeout: 5))
    let tools = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Tools'")).firstMatch
    XCTAssertTrue(tools.waitForExistence(timeout: 5))
    tools.tap()
    XCTAssertTrue(app.staticTexts["Web Search"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Files & Data"].exists)
  }

  #if os(macOS)
    func testMacComposerAndToolbarStayInsideTheNativeWindowLayout() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launch()

      let window = app.windows.firstMatch
      let splitter = app.splitters.firstMatch
      let attachment = app.buttons["chat.attachments"]
      let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
      let microphone = app.buttons["chat.microphone"]
      let send = app.buttons["chat.send"]
      XCTAssertTrue(window.waitForExistence(timeout: 10))
      XCTAssertTrue(splitter.waitForExistence(timeout: 5))
      XCTAssertTrue(attachment.waitForExistence(timeout: 5))
      XCTAssertTrue(composer.waitForExistence(timeout: 5))
      XCTAssertTrue(microphone.waitForExistence(timeout: 5))
      XCTAssertTrue(send.waitForExistence(timeout: 5))

      XCTAssertGreaterThanOrEqual(window.frame.width, 1_070)
      XCTAssertGreaterThanOrEqual(attachment.frame.minX, splitter.frame.maxX + 12)
      XCTAssertGreaterThan(composer.frame.width, 180)
      XCTAssertLessThanOrEqual(send.frame.maxX, window.frame.maxX - 12)
      for button in [attachment, microphone, send] {
        XCTAssertGreaterThanOrEqual(button.frame.width, 42)
        XCTAssertGreaterThanOrEqual(button.frame.height, 42)
      }
      XCTAssertGreaterThanOrEqual(send.frame.minX - microphone.frame.maxX, 8)
      XCTAssertEqual(app.toolbars.staticTexts.matching(identifier: "Chief").count, 0)

      composer.click()
      composer.typeText("Mac layout smoke test")
      XCTAssertTrue(send.isEnabled)
      XCTAssertLessThanOrEqual(send.frame.maxX, window.frame.maxX - 12)
      send.click()
      XCTAssertTrue(
        app.staticTexts["This is the native app’s offline test reply."].waitForExistence(
          timeout: 5))
    }

    func testMacEditorUsesAReadableNativeSheet() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launch()

      let create = app.buttons["sidebar.create"]
      XCTAssertTrue(create.waitForExistence(timeout: 10))
      create.click()
      let customBot = app.menuItems["Create a custom bot"]
      XCTAssertTrue(customBot.waitForExistence(timeout: 5))
      customBot.click()

      let sheet = app.sheets.firstMatch
      let name = app.textFields["Name"]
      let tagline = app.textFields["What this bot does"]
      XCTAssertTrue(sheet.waitForExistence(timeout: 5))
      XCTAssertTrue(name.waitForExistence(timeout: 5))
      XCTAssertTrue(tagline.waitForExistence(timeout: 5))
      XCTAssertGreaterThanOrEqual(sheet.frame.width, 670)
      XCTAssertGreaterThan(name.frame.minX, sheet.frame.minX + 20)
      XCTAssertLessThan(name.frame.maxX, sheet.frame.maxX - 20)
      XCTAssertGreaterThan(tagline.frame.minX, sheet.frame.minX + 20)
      XCTAssertLessThan(tagline.frame.maxX, sheet.frame.maxX - 20)
      XCTAssertTrue(app.staticTexts["Color"].exists)
      XCTAssertTrue(app.descendants(matching: .any)["Instructions"].firstMatch.exists)

      let close = app.buttons["Close"]
      XCTAssertTrue(close.isHittable)
      close.click()
      XCTAssertTrue(sheet.waitForNonExistence(timeout: 5))
    }
  #endif
}
