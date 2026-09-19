import XCTest

@MainActor final class HeyTimAppleUITests: XCTestCase {
  #if os(iOS)
    func testLaunchShowsChatListBeforeOpeningAConversation() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing", "--ui-testing-chat-list-launch"]
      app.launchForUITesting()

      let chief = app.staticTexts["Chief"].firstMatch
      XCTAssertTrue(chief.waitForExistence(timeout: 10))
      XCTAssertTrue(chief.isHittable)
      XCTAssertFalse(app.descendants(matching: .any)["chat.composer"].firstMatch.exists)

      chief.tap()
      XCTAssertTrue(
        app.descendants(matching: .any)["chat.composer"].firstMatch.waitForExistence(timeout: 10))
    }

    func testAssistantReplyUsesFullMobileTranscriptWidth() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launchForUITesting()

      let transcript = app.scrollViews["chat.transcript"]
      let reply = app.descendants(matching: .any)["chat.message.content.m2"].firstMatch
      let userMessage = app.descendants(matching: .any)["chat.message.content.m1"].firstMatch
      XCTAssertTrue(reply.waitForExistence(timeout: 10))
      XCTAssertTrue(transcript.exists)
      let screenshot = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
      screenshot.name = "Assistant reply width on iPhone"
      screenshot.lifetime = .keepAlways
      add(screenshot)
      XCTAssertTrue(reply.isHittable)
      XCTAssertGreaterThanOrEqual(reply.frame.width, transcript.frame.width - 50)
      XCTAssertLessThanOrEqual(reply.frame.minX - transcript.frame.minX, 20)
      XCTAssertLessThanOrEqual(transcript.frame.maxX - reply.frame.maxX, 40)
      XCTAssertLessThan(userMessage.frame.width, reply.frame.width)
    }

    func testDelayedBotSwitchShowsAnswerWithoutScrolling() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing", "--ui-testing-delayed-bot-switch"]
      app.launchForUITesting()

      let sidebar = app.buttons["Hey Tim"]
      XCTAssertTrue(sidebar.waitForExistence(timeout: 10))
      sidebar.tap()
      let researcher = app.staticTexts["Research Bot"].firstMatch
      XCTAssertTrue(researcher.waitForExistence(timeout: 5))
      researcher.tap()

      let finalLine = app.staticTexts["Research Bot answer visible after loading."]
      let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
      XCTAssertTrue(finalLine.waitForExistence(timeout: 10))
      XCTAssertTrue(finalLine.isHittable)
      XCTAssertLessThan(finalLine.frame.maxY, composer.frame.minY)

      sidebar.tap()
      app.staticTexts["Chief"].firstMatch.tap()
      sidebar.tap()
      researcher.tap()
      XCTAssertTrue(finalLine.waitForExistence(timeout: 10))
      XCTAssertTrue(finalLine.isHittable)
      XCTAssertLessThan(finalLine.frame.maxY, composer.frame.minY)
    }
  #endif

  #if os(iOS)
  func testBotEditorCanChooseGmailAccountsIndependently() {
    let app = XCUIApplication()
    app.launchArguments = [
      "--ui-testing", "--ui-testing-multiple-connections",
      "--ui-testing-sheet=bot-editor",
    ]
    app.launchForUITesting()

    let toolsLink = app.descendants(matching: .any)["bot.tools-and-skills"].firstMatch
    XCTAssertTrue(toolsLink.waitForExistence(timeout: 10))
    toolsLink.tap()

    let firstGmail = app.switches["bot.tool.connection_gmail_alpha"]
    let secondGmail = app.switches["bot.tool.connection_gmail_beta"]
    XCTAssertTrue(firstGmail.waitForExistence(timeout: 5))
    XCTAssertTrue(secondGmail.exists)
    XCTAssertTrue(firstGmail.label.contains("alpha@example.com"))
    XCTAssertTrue(secondGmail.label.contains("beta@example.com"))

    firstGmail.coordinate(withNormalizedOffset: CGVector(dx: 0.86, dy: 0.5)).tap()
    XCTAssertEqual(firstGmail.value as? String, "1")
    XCTAssertEqual(secondGmail.value as? String, "0")
    secondGmail.coordinate(withNormalizedOffset: CGVector(dx: 0.86, dy: 0.5)).tap()
    XCTAssertEqual(secondGmail.value as? String, "1")
    firstGmail.coordinate(withNormalizedOffset: CGVector(dx: 0.86, dy: 0.5)).tap()
    XCTAssertEqual(firstGmail.value as? String, "0")
    XCTAssertEqual(secondGmail.value as? String, "1")
  }
  #endif

  func testEveryFeatureSheetCanOpenAndCloseWithoutSelfDismissing() {
    let featureSheets = [
      (argument: "bot-library", marker: "Add a Bot"),
      (argument: "bot-editor", marker: "New bot"),
      (argument: "group-editor", marker: "New group"),
      (argument: "schedules", marker: "Scheduled tasks"),
      (argument: "schedule-runs", marker: "Run history"),
      (argument: "memory", marker: "Memory"),
      (argument: "account", marker: "Settings"),
      (argument: "skills", marker: "Tools & Skills"),
      (argument: "skill-editor", marker: "New skill"),
      (argument: "connections", marker: "Couldn’t Load Accounts"),
      (argument: "documents", marker: "Documents"),
      (argument: "browser", marker: "Secure Browser"),
      (argument: "share", marker: "Share"),
    ]

    for featureSheet in featureSheets {
      XCTContext.runActivity(named: featureSheet.argument) { _ in
        let app = XCUIApplication()
        app.launchArguments = [
          "--ui-testing", "--ui-testing-sheet=\(featureSheet.argument)",
        ]
        app.launchForUITesting()

        let marker = app.staticTexts[featureSheet.marker]
        XCTAssertTrue(
          marker.waitForExistence(timeout: 10),
          "The \(featureSheet.argument) sheet did not remain presented.")
        let close = app.buttons["sheet.close"]
        XCTAssertTrue(
          close.waitForExistence(timeout: 5),
          "The \(featureSheet.argument) sheet did not expose its dismissal control.")
        XCTAssertTrue(marker.exists)
        close.tap()
        XCTAssertTrue(app.buttons["chat.details"].waitForExistence(timeout: 5))
        app.terminate()
      }
    }
  }

  func testNativeSignInMatchesTheHeyTimFlow() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing-auth"]
    app.launchForUITesting()

    XCTAssertTrue(app.staticTexts["Hey Tim"].firstMatch.waitForExistence(timeout: 10))
    XCTAssertTrue(app.staticTexts["Welcome back"].waitForExistence(timeout: 5))
    XCTAssertTrue(app.textFields["Email address"].exists)
    XCTAssertTrue(app.buttons["Continue"].exists)
    XCTAssertTrue(app.descendants(matching: .any)["Need an invite? Request beta access"].exists)
  }

  func testNativeConversationLaunchesAndSendsAMessage() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launchForUITesting()

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
      app.buttons["Hey Tim"].tap()
    #endif
    XCTAssertTrue(app.searchFields["Search chats"].waitForExistence(timeout: 5))
    #if os(macOS)
      let chief = app.descendants(matching: .any)["sidebar.title.bot.chief"].firstMatch
    #else
      let chief = app.staticTexts["Chief"].firstMatch
    #endif
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
    app.launchForUITesting()

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
    app.launchForUITesting()

    let latestStep = app.descendants(matching: .any)["chat.activity.step.9"].firstMatch
    let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
    XCTAssertTrue(latestStep.waitForExistence(timeout: 10))
    XCTAssertTrue(composer.waitForExistence(timeout: 5))
    XCTAssertTrue(latestStep.isHittable)
    XCTAssertTrue(composer.isHittable)
    XCTAssertFalse(app.staticTexts["Checking `README.md` for the intended release workflow."].exists)
  }

  func testConversationAppearsAfterLoadingAndClearsStaleWorkingStatus() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-delayed-conversation"]
    app.launchForUITesting()

    let latestMessage = app.staticTexts["Latest message before send."]
    let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
    let sidebarChief = app.descendants(matching: .any)["sidebar.title.bot.chief"].firstMatch
    XCTAssertTrue(latestMessage.waitForExistence(timeout: 10))
    XCTAssertTrue(composer.waitForExistence(timeout: 5))
    XCTAssertTrue(latestMessage.isHittable)
    XCTAssertLessThan(latestMessage.frame.maxY, composer.frame.minY)
    #if os(iOS)
      app.buttons["Hey Tim"].tap()
    #endif
    XCTAssertTrue(sidebarChief.waitForExistence(timeout: 5))
    XCTAssertFalse(sidebarChief.label.localizedCaseInsensitiveContains("working"))
  }

  func testGroupProgressUsesCompactStatusRowsWithoutEmptyReplyBubbles() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-group-progress"]
    app.launchForUITesting()

    let running = app.descendants(matching: .any)["chat.progress.running"].firstMatch
    let queued = app.descendants(matching: .any)["chat.progress.pending"].firstMatch
    let waiting = app.descendants(matching: .any)["chat.progress.waiting"].firstMatch
    XCTAssertTrue(running.waitForExistence(timeout: 10))
    XCTAssertTrue(queued.waitForExistence(timeout: 5))
    XCTAssertTrue(waiting.waitForExistence(timeout: 5))
    XCTAssertTrue(app.staticTexts["Comparing the strongest options and supporting evidence."].exists)
    XCTAssertTrue(app.staticTexts["Processing…"].exists)
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
      let sidebarGroup =
        app.descendants(matching: .any)["sidebar.title.group.research-team"].firstMatch
      XCTAssertTrue(sidebarGroup.waitForExistence(timeout: 5))
      XCTAssertTrue(sidebarGroup.label.localizedCaseInsensitiveContains("working"))
      let replyPicker = app.descendants(matching: .any)["chat.replyPicker"]
      XCTAssertTrue(replyPicker.waitForExistence(timeout: 5))
      XCTAssertTrue(replyPicker.isHittable)
    #endif
  }

  func testMessageMarkdownUsesNativeBlockFormatting() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-markdown"]
    app.launchForUITesting()

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
    app.launchForUITesting()

    let attachmentMenu = app.descendants(matching: .any)["chat.attachments"].firstMatch
    XCTAssertTrue(attachmentMenu.waitForExistence(timeout: 10))
    let microphone = app.buttons["chat.microphone"]
    XCTAssertTrue(microphone.waitForExistence(timeout: 5))
    XCTAssertTrue(microphone.isHittable)
    attachmentMenu.tap()

    XCTAssertTrue(app.descendants(matching: .any)["Photo Library"].firstMatch.waitForExistence(timeout: 5))
    XCTAssertTrue(app.descendants(matching: .any)["Choose Files"].firstMatch.exists)
  }

  func testConversationDetailsUsesPlatformNavigationAndCanClose() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launchForUITesting()

    let details = app.buttons["chat.details"]
    XCTAssertTrue(details.waitForExistence(timeout: 10))
    XCTAssertFalse(app.buttons["inspector.save"].exists)
    #if os(macOS)
      XCTAssertFalse(app.toolbars.staticTexts["Details"].exists)
    #endif
    details.tap()
    let inspectorBack = app.buttons["inspector.back"]

    #if os(iOS)
      XCTAssertTrue(app.navigationBars["Details"].waitForExistence(timeout: 5))
      XCTAssertTrue(inspectorBack.exists)
      XCTAssertTrue(inspectorBack.isHittable)
      XCTAssertFalse(app.buttons["Done"].exists)
    #else
      let title = app.toolbars.staticTexts["Details"]
      XCTAssertTrue(title.waitForExistence(timeout: 5))
      XCTAssertFalse(app.sheets.firstMatch.exists)
      XCTAssertFalse(app.buttons["chat.details"].exists)
      XCTAssertTrue(inspectorBack.exists)
      XCTAssertTrue(inspectorBack.isHittable)
      XCTAssertFalse(app.buttons["Done"].exists)
      XCTAssertGreaterThan(inspectorBack.frame.minX, app.splitters.firstMatch.frame.maxX)
      XCTAssertLessThan(inspectorBack.frame.midX, app.windows.firstMatch.frame.midX)
      XCTAssertLessThan(abs(title.frame.midY - inspectorBack.frame.midY), 20)
      XCTAssertEqual(app.splitters.count, 1)
      let headerScreenshot = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
      headerScreenshot.name = "Details uses the shared navigation header"
      headerScreenshot.lifetime = .keepAlways
      add(headerScreenshot)
    #endif

    inspectorBack.tap()
    XCTAssertTrue(inspectorBack.waitForNonExistence(timeout: 5))
    XCTAssertTrue(app.buttons["chat.details"].waitForExistence(timeout: 5))
    app.buttons["chat.details"].tap()
    XCTAssertTrue(app.buttons["inspector.back"].waitForExistence(timeout: 5))

    XCTAssertTrue(app.textFields["Name"].exists)
    let promptEditor = app.buttons["bot.prompt.editor"]
    for _ in 0..<2 where !promptEditor.exists { app.swipeUp() }
    XCTAssertTrue(promptEditor.exists)
    XCTAssertTrue(app.buttons["inspector.save"].exists)
    XCTAssertFalse(app.buttons["Edit Bot"].exists)
    let toolsAndSkills = app.buttons["bot.tools-and-skills"]
    let conversationLinks = [
      "conversation.schedules", "conversation.runs", "conversation.share",
      "conversation.documents", "conversation.browser", "conversation.memory",
    ].map { app.buttons[$0] }
    let memory = app.buttons["conversation.memory"]
    for _ in 0..<4 where !toolsAndSkills.exists || !memory.exists { app.swipeUp() }
    XCTAssertTrue(toolsAndSkills.exists)
    for link in conversationLinks {
      XCTAssertTrue(link.exists)
    }

    memory.tap()
    XCTAssertTrue(app.staticTexts["Chief Memory"].waitForExistence(timeout: 5))
    let rootLinksDisappear = XCTNSPredicateExpectation(
      predicate: NSPredicate(format: "exists == false"),
      object: app.buttons["conversation.schedules"])
    wait(for: [rootLinksDisappear], timeout: 5)
  }

  func testAccountSettingsUsesTheHeyTimLayout() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launchForUITesting()

    #if os(iOS)
      let sidebar = app.buttons["Hey Tim"]
      XCTAssertTrue(sidebar.waitForExistence(timeout: 10))
      sidebar.tap()
    #endif
    let create = app.descendants(matching: .any)["sidebar.create"].firstMatch
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
    for title in ["Memory", "Add a Bot", "Tools & Skills", "Connected Accounts"] {
      XCTAssertTrue(app.descendants(matching: .any)[title].firstMatch.exists)
    }
    XCTAssertTrue(app.descendants(matching: .any)["settings.appearance"].exists)
    XCTAssertTrue(app.descendants(matching: .any)["settings.text-size"].exists)
    #if os(iOS)
      XCTAssertTrue(app.buttons["Close"].exists)
      XCTAssertFalse(app.buttons["Done"].exists)
    #else
      let close = app.buttons["sheet.close"]
      let title = app.staticTexts["Settings"]
      XCTAssertTrue(close.exists)
      XCTAssertTrue(close.isHittable)
      XCTAssertLessThan(close.frame.midX, title.frame.midX)
      XCTAssertGreaterThan(close.frame.minX, app.splitters.firstMatch.frame.maxX)
      XCTAssertLessThan(close.frame.midX, app.windows.firstMatch.frame.midX)
      XCTAssertFalse(app.sheets.firstMatch.exists)
      XCTAssertFalse(app.buttons["Done"].exists)
      XCTAssertEqual(app.windows.count, 1)
    #endif

    let exportMemory = app.buttons["Export Memory"]
    for _ in 0..<4 where !exportMemory.exists { app.swipeUp() }
    XCTAssertTrue(exportMemory.waitForExistence(timeout: 5))

    #if os(macOS)
      let aboutValue = app.staticTexts["Hey Tim for Apple"]
    #else
      let aboutValue = app.staticTexts["App, Hey Tim for Apple"]
    #endif
    for _ in 0..<4 where !aboutValue.exists { app.swipeUp() }
    XCTAssertTrue(aboutValue.waitForExistence(timeout: 5))
    #if os(macOS)
      XCTAssertTrue(app.staticTexts["iPhone + Mac"].exists)
    #else
      XCTAssertTrue(app.staticTexts["Platforms, iPhone + Mac"].exists)
    #endif
    let version = app.descendants(matching: .any)["settings.version"]
    for _ in 0..<4 where !version.exists { app.swipeUp() }
    XCTAssertTrue(version.waitForExistence(timeout: 5))
  }

  #if os(macOS)
    func testMacTextSizeUpdatesSettingsAndKeepsSidebarUsable() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launchForUITesting()

      let sidebarTitle = app.descendants(matching: .any)["sidebar.title.bot.chief"].firstMatch
      let settings = app.buttons["sidebar.settings"]
      XCTAssertTrue(sidebarTitle.waitForExistence(timeout: 10))
      XCTAssertTrue(settings.waitForExistence(timeout: 5))

      func chooseTextSize(_ name: String) {
        let picker = app.descendants(matching: .any)["settings.text-size"]
        XCTAssertTrue(picker.waitForExistence(timeout: 5))
        picker.click()
        let option = app.menuItems[name]
        XCTAssertTrue(option.waitForExistence(timeout: 5))
        option.click()
      }

      settings.click()
      chooseTextSize("Standard")
      let standardSettingsHeight = app.descendants(matching: .any)["Memory"].firstMatch.frame.height
      app.buttons["sheet.close"].click()
      XCTAssertTrue(sidebarTitle.isHittable)

      settings.click()
      chooseTextSize("Extra Large")
      let extraLargeSettingsHeight = app.descendants(matching: .any)["Memory"].firstMatch.frame.height
      app.buttons["sheet.close"].click()
      XCTAssertTrue(sidebarTitle.isHittable)

      XCTAssertGreaterThan(extraLargeSettingsHeight, standardSettingsHeight)

      settings.click()
      chooseTextSize("Standard")
      app.buttons["sheet.close"].click()
    }
  #endif

  #if os(iOS)
    func testConnectedAccountsUsesSettingsBackButtonWithoutARedundantTitleOrCloseButton() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launchForUITesting()

      let sidebar = app.buttons["Hey Tim"]
      XCTAssertTrue(sidebar.waitForExistence(timeout: 10))
      sidebar.tap()
      let settings = app.buttons["sidebar.settings"]
      XCTAssertTrue(settings.waitForExistence(timeout: 10))
      settings.tap()

      let connectedAccounts = app.staticTexts["Connected Accounts"]
      XCTAssertTrue(connectedAccounts.waitForExistence(timeout: 5))
      connectedAccounts.tap()

      let accountsLoaded = app.staticTexts["Accounts"].waitForExistence(timeout: 5)
      let accountsUnavailable =
        app.staticTexts["Couldn’t Load Accounts"].waitForExistence(timeout: accountsLoaded ? 0 : 5)
      XCTAssertTrue(accountsLoaded || accountsUnavailable)
      XCTAssertTrue(app.navigationBars.buttons["Settings"].exists)
      XCTAssertFalse(app.buttons["Close"].exists)
      XCTAssertFalse(app.staticTexts["Connected Accounts"].exists)
    }
  #endif

  func testAddBotGalleryExplainsTheConfiguredSkillsToolsAndPrompt() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launchForUITesting()

    #if os(iOS)
      app.buttons["Hey Tim"].tap()
    #endif
    let create = app.descendants(matching: .any)["sidebar.create"].firstMatch
    XCTAssertTrue(create.waitForExistence(timeout: 10))
    XCTAssertFalse(app.buttons["sidebar.addBot"].exists)
    create.tap()
    let addBot = app.descendants(matching: .any)["Add a bot"].firstMatch
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
    XCTAssertTrue(app.descendants(matching: .any)["View Full Instructions"].firstMatch.exists)
    XCTAssertTrue(app.buttons["Add Bot"].exists)
  }

  func testCreatingCustomBotKeepsTheEditorPresented() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launchForUITesting()

    #if os(iOS)
      let sidebar = app.buttons["Hey Tim"]
      XCTAssertTrue(sidebar.waitForExistence(timeout: 10))
      sidebar.tap()
    #endif
    let create = app.descendants(matching: .any)["sidebar.create"].firstMatch
    XCTAssertTrue(create.waitForExistence(timeout: 10))
    create.tap()
    let addBot = app.descendants(matching: .any)["Add a bot"].firstMatch
    XCTAssertTrue(addBot.waitForExistence(timeout: 5))
    addBot.tap()

    let customBot = app.buttons["Create a Custom Bot"]
    XCTAssertTrue(customBot.waitForExistence(timeout: 5))
    customBot.tap()

    XCTAssertTrue(app.staticTexts["New bot"].waitForExistence(timeout: 5))
    let name = app.textFields["Name"]
    XCTAssertTrue(name.waitForExistence(timeout: 5))
    name.tap()
    name.typeText("Trip planner")
    XCTAssertEqual(name.value as? String, "Trip planner")
    XCTAssertFalse(app.buttons["Close"].exists)
  }

  func testToolsAndSkillsShowsBothSkillsAndBuiltInTools() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launchForUITesting()

    #if os(iOS)
      app.buttons["Hey Tim"].tap()
    #endif
    XCTAssertTrue(app.buttons["sidebar.settings"].waitForExistence(timeout: 10))
    app.buttons["sidebar.settings"].tap()
    let toolsAndSkills = app.descendants(matching: .any)["Tools & Skills"].firstMatch
    XCTAssertTrue(toolsAndSkills.waitForExistence(timeout: 5))
    toolsAndSkills.tap()

    let research = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Deep Research'"))
      .firstMatch
    XCTAssertTrue(research.waitForExistence(timeout: 5))
    #if os(macOS)
      let tools = app.radioButtons.matching(NSPredicate(format: "label BEGINSWITH 'Tools'"))
        .firstMatch
    #else
      let tools = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Tools'"))
        .firstMatch
    #endif
    XCTAssertTrue(tools.waitForExistence(timeout: 5))
    tools.tap()
    XCTAssertTrue(
      app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Web Search'"))
        .firstMatch.waitForExistence(timeout: 5))
    XCTAssertTrue(
      app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Files & Data'"))
        .firstMatch.exists)
  }

  func testCreatingSkillKeepsTheEditorPresented() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing"]
    app.launchForUITesting()

    #if os(iOS)
      let sidebar = app.buttons["Hey Tim"]
      XCTAssertTrue(sidebar.waitForExistence(timeout: 10))
      sidebar.tap()
    #endif
    let settings = app.buttons["sidebar.settings"]
    XCTAssertTrue(settings.waitForExistence(timeout: 10))
    settings.tap()
    let toolsAndSkills = app.descendants(matching: .any)["Tools & Skills"].firstMatch
    XCTAssertTrue(toolsAndSkills.waitForExistence(timeout: 5))
    toolsAndSkills.tap()

    let addSkill = app.buttons["Add Skill"]
    XCTAssertTrue(addSkill.waitForExistence(timeout: 5))
    addSkill.tap()
    let createSkill = app.buttons["Create Skill"]
    XCTAssertTrue(createSkill.waitForExistence(timeout: 5))
    createSkill.tap()

    XCTAssertTrue(app.staticTexts["New skill"].waitForExistence(timeout: 5))
    let name = app.textFields["Name"]
    XCTAssertTrue(name.waitForExistence(timeout: 5))
    name.tap()
    name.typeText("Research helper")
    XCTAssertEqual(name.value as? String, "Research helper")
    XCTAssertFalse(app.buttons["Close"].exists)
  }

  func testCreatingScheduledTaskKeepsTheEditorPresented() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-sheet=schedules"]
    app.launchForUITesting()

    XCTAssertTrue(app.staticTexts["Scheduled tasks"].waitForExistence(timeout: 10))
    let create = app.buttons["New"]
    XCTAssertTrue(create.waitForExistence(timeout: 5))
    create.tap()

    XCTAssertTrue(app.staticTexts["New task"].waitForExistence(timeout: 5))
    let name = app.textFields["Name"]
    XCTAssertTrue(name.waitForExistence(timeout: 5))
    name.tap()
    name.typeText("Daily summary")
    XCTAssertEqual(name.value as? String, "Daily summary")
    XCTAssertFalse(app.buttons["Close"].exists)
  }

  func testScrollToLatestControlAndSendingReturnToTheBottom() {
    let app = XCUIApplication()
    app.launchArguments = ["--ui-testing", "--ui-testing-scroll"]
    app.launchForUITesting()

    let transcript = app.scrollViews["chat.transcript"]
    let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
    let latestBeforeSend = app.staticTexts["Latest message before send."]
    let scrollToLatest = app.buttons["chat.scroll-to-latest"]
    XCTAssertTrue(transcript.waitForExistence(timeout: 10))
    XCTAssertTrue(composer.waitForExistence(timeout: 5))
    XCTAssertTrue(latestBeforeSend.waitForExistence(timeout: 5))
    XCTAssertTrue(latestBeforeSend.isHittable)

    transcript.swipeDown(velocity: .fast)
    transcript.swipeDown(velocity: .fast)
    XCTAssertTrue(scrollToLatest.waitForExistence(timeout: 5))
    XCTAssertTrue(scrollToLatest.isHittable)
    scrollToLatest.tap()
    XCTAssertTrue(latestBeforeSend.waitForExistence(timeout: 5))
    XCTAssertTrue(latestBeforeSend.isHittable)

    transcript.swipeDown(velocity: .fast)
    transcript.swipeDown(velocity: .fast)
    XCTAssertTrue(scrollToLatest.waitForExistence(timeout: 5))
    composer.tap()
    composer.typeText("Return to the latest message")
    app.buttons["chat.send"].tap()

    let reply = app.staticTexts["This is the native app’s offline test reply."]
    XCTAssertTrue(reply.waitForExistence(timeout: 5))
    XCTAssertTrue(reply.isHittable)
    XCTAssertLessThan(reply.frame.maxY, composer.frame.minY)
    XCTAssertFalse(scrollToLatest.exists)
  }

  #if os(macOS)
    func testMacSwitchingFromGroupDetailsToBotDismissesOldCover() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing", "--ui-testing-history-switch"]
      app.launchForUITesting()

      let group = app.buttons["sidebar.title.group.research-team"]
      let chief = app.buttons["sidebar.title.bot.chief"]
      let researcher = app.buttons["sidebar.title.bot.researcher"]
      let details = app.buttons["chat.details"]
      let back = app.buttons["inspector.back"]
      XCTAssertTrue(group.waitForExistence(timeout: 10))
      XCTAssertTrue(chief.exists)
      XCTAssertTrue(researcher.exists)

      for _ in 0..<3 {
        XCTAssertTrue(app.staticTexts["Group answer remains available after switching."].waitForExistence(timeout: 5))
        XCTAssertTrue(details.waitForExistence(timeout: 5))
        details.click()
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Research Team"].exists)

        chief.click()
        XCTAssertTrue(back.waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.toolbars.staticTexts["Chief"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Can you summarize the launch plan?"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["chat.composer"].firstMatch.exists)
        XCTAssertEqual(app.splitters.count, 1)

        details.click()
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        researcher.click()
        XCTAssertTrue(back.waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.toolbars.staticTexts["Research Bot"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Research Bot answer remains available after switching."].waitForExistence(timeout: 5))

        details.click()
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        group.click()
        XCTAssertTrue(back.waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.toolbars.staticTexts["Research Team"].waitForExistence(timeout: 5))
      }
    }

    func testMacSwitchingBotsWhileDetailsIsOpenKeepsNavigationStable() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing", "--ui-testing-two-bots"]
      app.launchForUITesting()

      let chief = app.buttons["sidebar.title.bot.chief"]
      let researcher = app.buttons["sidebar.title.bot.researcher"]
      let details = app.buttons["chat.details"]
      let back = app.buttons["inspector.back"]
      XCTAssertTrue(chief.waitForExistence(timeout: 10))
      XCTAssertTrue(researcher.exists)

      for (nextBot, name) in [(researcher, "Research Bot"), (chief, "Chief"),
        (researcher, "Research Bot")]
      {
        XCTAssertTrue(details.waitForExistence(timeout: 5))
        details.click()
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        nextBot.click()
        XCTAssertTrue(back.waitForNonExistence(timeout: 5))
        XCTAssertTrue(app.toolbars.staticTexts[name].waitForExistence(timeout: 5))
        XCTAssertTrue(app.descendants(matching: .any)["chat.composer"].firstMatch.exists)
        XCTAssertEqual(app.splitters.count, 1)
      }

      details.click()
      XCTAssertTrue(back.waitForExistence(timeout: 5))
      XCTAssertEqual(app.textFields["Name"].value as? String, "Research Bot")
      let schedules = app.buttons["conversation.schedules"]
      XCTAssertTrue(schedules.waitForExistence(timeout: 5))
      schedules.click()
      XCTAssertTrue(app.toolbars.staticTexts["Scheduled tasks"].waitForExistence(timeout: 5))
      chief.click()
      XCTAssertTrue(details.waitForExistence(timeout: 5))
      XCTAssertFalse(app.toolbars.staticTexts["Scheduled tasks"].exists)
      XCTAssertEqual(app.splitters.count, 1)

      details.click()
      let toolsAndSkills = app.buttons["bot.tools-and-skills"]
      XCTAssertTrue(toolsAndSkills.waitForExistence(timeout: 5))
      toolsAndSkills.click()
      XCTAssertTrue(app.toolbars.staticTexts["Tools & Skills"].waitForExistence(timeout: 5))
      researcher.click()
      XCTAssertTrue(details.waitForExistence(timeout: 5))
      XCTAssertFalse(app.toolbars.staticTexts["Tools & Skills"].exists)

      details.click()
      app.buttons["bot.prompt.editor"].click()
      XCTAssertTrue(app.toolbars.staticTexts["Bot Prompt"].waitForExistence(timeout: 5))
      chief.click()
      XCTAssertTrue(details.waitForExistence(timeout: 5))
      XCTAssertFalse(app.toolbars.staticTexts["Bot Prompt"].exists)
      XCTAssertEqual(app.splitters.count, 1)
    }

    func testMacDetailsCoverChatAndRemainStableWhenResizing() {
      for group in [false, true] {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-testing"] + (group ? ["--ui-testing-group-progress"] : [])
        app.launchForUITesting()

        let window = app.windows.firstMatch
        let details = app.buttons["chat.details"]
        let search = app.searchFields["Search chats"]
        let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
        XCTAssertTrue(details.waitForExistence(timeout: 10))
        XCTAssertTrue(search.exists)
        let sidebarFrame = search.frame
        let splitterX = app.splitters.firstMatch.frame.minX
        composer.click()
        composer.typeText("Keep this draft while inspecting")

        details.click()
        let back = app.buttons["inspector.back"]
        XCTAssertTrue(back.waitForExistence(timeout: 5))
        XCTAssertEqual(app.splitters.count, 1, "Details must not add a resizable inspector column.")
        XCTAssertEqual(search.frame.minX, sidebarFrame.minX, accuracy: 2)
        XCTAssertEqual(search.frame.width, sidebarFrame.width, accuracy: 2)
        XCTAssertEqual(app.splitters.firstMatch.frame.minX, splitterX, accuracy: 2)
        XCTAssertFalse(composer.exists, "The covered chat must not remain accessible.")
        XCTAssertFalse(app.sheets.firstMatch.exists)

        for offset in [CGVector(dx: -40, dy: -60), CGVector(dx: 100, dy: 60)] {
          let previousSize = window.frame.size
          let corner = window.coordinate(withNormalizedOffset: CGVector(dx: 1, dy: 1))
            .withOffset(CGVector(dx: -2, dy: -2))
          corner.click(forDuration: 0.2, thenDragTo: corner.withOffset(offset))
          XCTAssertNotEqual(window.frame.size, previousSize, "The test must actually resize the window.")
          XCTAssertTrue(back.isHittable)
          XCTAssertEqual(app.splitters.count, 1)
          XCTAssertEqual(search.frame.width, sidebarFrame.width, accuracy: 2)
          XCTAssertGreaterThan(back.frame.minX, app.splitters.firstMatch.frame.maxX)
          XCTAssertLessThan(back.frame.midX, window.frame.midX)
        }

        // The remaining divider belongs only to the original chat list. Drag it
        // with Details open too, covering the NSSplitView interaction in the crash.
        let divider = app.splitters.firstMatch.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        divider.click(forDuration: 0.2, thenDragTo: divider.withOffset(CGVector(dx: 20, dy: 0)))
        XCTAssertTrue(back.isHittable)
        XCTAssertEqual(app.splitters.count, 1)
        let screenshot = XCTAttachment(screenshot: window.screenshot())
        screenshot.name = group ? "Group Details after resizing" : "Bot Details after resizing"
        screenshot.lifetime = .keepAlways
        add(screenshot)

        back.click()
        XCTAssertTrue(composer.waitForExistence(timeout: 5))
        XCTAssertEqual(composer.value as? String, "Keep this draft while inspecting")
        XCTAssertTrue(details.isHittable)
        app.terminate()
      }
    }

    func testMacFeaturePagesCoverChatWithoutMovingSidebar() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launchForUITesting()
      let search = app.searchFields["Search chats"]
      XCTAssertTrue(search.waitForExistence(timeout: 10))
      let sidebarFrame = search.frame
      let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
      composer.click()
      composer.typeText("Keep this draft behind Settings")
      app.buttons["sidebar.settings"].click()
      let back = app.buttons["sheet.close"]
      XCTAssertTrue(back.waitForExistence(timeout: 5))
      let settingsTitle = app.toolbars.staticTexts["Settings"]
      XCTAssertTrue(settingsTitle.exists)
      XCTAssertLessThan(abs(settingsTitle.frame.midY - back.frame.midY), 20)
      XCTAssertLessThan(settingsTitle.frame.minX - back.frame.maxX, 40)
      let settingsScreenshot = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
      settingsScreenshot.name = "Settings uses the shared navigation header"
      settingsScreenshot.lifetime = .keepAlways
      add(settingsScreenshot)
      XCTAssertEqual(search.frame.minX, sidebarFrame.minX, accuracy: 2)
      XCTAssertEqual(search.frame.width, sidebarFrame.width, accuracy: 2)
      XCTAssertEqual(app.splitters.count, 1)
      XCTAssertFalse(app.descendants(matching: .any)["chat.composer"].firstMatch.exists)
      XCTAssertFalse(app.buttons["chat.details"].exists)
      back.click()
      XCTAssertTrue(app.buttons["chat.details"].waitForExistence(timeout: 5))
      XCTAssertEqual(composer.value as? String, "Keep this draft behind Settings")

      app.buttons["sidebar.settings"].click()
      app.buttons["Tools & Skills"].click()
      XCTAssertTrue(app.staticTexts["Tools & Skills"].waitForExistence(timeout: 5))
      let toolsScreenshot = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
      toolsScreenshot.name = "Tools and Skills shares the navigation header"
      toolsScreenshot.lifetime = .keepAlways
      add(toolsScreenshot)
      app.buttons["sidebar.title.bot.chief"].click()
      XCTAssertTrue(app.buttons["chat.details"].waitForExistence(timeout: 5))
      XCTAssertFalse(app.buttons["sheet.close"].exists)
      XCTAssertEqual(composer.value as? String, "Keep this draft behind Settings")
    }

    func testMacSavingRootBotEditorReturnsToChat() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launchForUITesting()
      let create = app.menuButtons["sidebar.create"]
      XCTAssertTrue(create.waitForExistence(timeout: 10))
      create.click()
      app.menuItems["Create a custom bot"].click()
      let name = app.textFields["Name"]
      XCTAssertTrue(name.waitForExistence(timeout: 10))
      let back = app.buttons["sheet.close"]
      XCTAssertGreaterThan(back.frame.minX, app.splitters.firstMatch.frame.maxX)
      XCTAssertLessThan(back.frame.midX, app.windows.firstMatch.frame.midX)
      name.click()
      name.typeText("Local resize test bot")
      XCTAssertEqual(name.value as? String, "Local resize test bot")
      app.buttons["bot.prompt.editor"].click()
      let prompt = app.textViews["Bot prompt"]
      XCTAssertTrue(prompt.waitForExistence(timeout: 5))
      prompt.click()
      prompt.typeText("Help with local user interface testing.")
      XCTAssertEqual(prompt.value as? String, "Help with local user interface testing.")
      app.buttons["Done"].click()
      XCTAssertEqual(name.value as? String, "Local resize test bot")
      let save = app.buttons["Save"]
      XCTAssertTrue(save.isEnabled)
      save.click()
      XCTAssertTrue(app.buttons["chat.details"].waitForExistence(timeout: 5))
      XCTAssertFalse(app.buttons["sheet.close"].exists)
    }

    func testMacComposerAndToolbarStayInsideTheNativeWindowLayout() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launchForUITesting()

      let window = app.windows.firstMatch
      let splitter = app.splitters.firstMatch
      let attachment = app.menuButtons["chat.attachments"]
      let composer = app.descendants(matching: .any)["chat.composer"].firstMatch
      let microphone = app.buttons["chat.microphone"]
      let send = app.buttons["chat.send"]
      XCTAssertTrue(window.waitForExistence(timeout: 10))
      XCTAssertTrue(splitter.waitForExistence(timeout: 5))
      XCTAssertTrue(attachment.waitForExistence(timeout: 5))
      XCTAssertTrue(composer.waitForExistence(timeout: 5))
      XCTAssertTrue(microphone.waitForExistence(timeout: 5))
      XCTAssertTrue(send.waitForExistence(timeout: 5))

      XCTAssertGreaterThanOrEqual(window.frame.width, 1_150)
      XCTAssertGreaterThanOrEqual(attachment.frame.minX, splitter.frame.maxX + 12)
      XCTAssertGreaterThan(composer.frame.width, 180)
      XCTAssertLessThanOrEqual(send.frame.maxX, window.frame.maxX - 12)
      for button in [attachment, microphone, send] {
        XCTAssertGreaterThanOrEqual(button.frame.width, 42)
        XCTAssertGreaterThanOrEqual(button.frame.height, 42)
      }
      XCTAssertEqual(attachment.frame.width, microphone.frame.width, accuracy: 1)
      XCTAssertEqual(attachment.frame.height, microphone.frame.height, accuracy: 1)
      XCTAssertEqual(send.frame.width, microphone.frame.width, accuracy: 1)
      XCTAssertEqual(send.frame.height, microphone.frame.height, accuracy: 1)
      XCTAssertGreaterThanOrEqual(send.frame.minX - microphone.frame.maxX, 8)
      XCTAssertTrue(app.toolbars.staticTexts["Chief"].exists)

      composer.click()
      composer.typeText("Mac layout smoke test")
      XCTAssertTrue(send.isEnabled)
      XCTAssertLessThanOrEqual(send.frame.maxX, window.frame.maxX - 12)
      send.click()
      XCTAssertTrue(
        app.staticTexts["This is the native app’s offline test reply."].waitForExistence(
          timeout: 5))
    }

    func testMacEditorUsesAReadableSlideOut() {
      let app = XCUIApplication()
      app.launchArguments = ["--ui-testing"]
      app.launchForUITesting()

      let create = app.menuButtons["sidebar.create"]
      XCTAssertTrue(create.waitForExistence(timeout: 10))
      create.click()
      let customBot = app.menuItems["Create a custom bot"]
      XCTAssertTrue(customBot.waitForExistence(timeout: 5))
      customBot.click()

      let window = app.windows.firstMatch
      let name = app.textFields["Name"]
      let tagline = app.textFields["What this bot does"]
      XCTAssertTrue(name.waitForExistence(timeout: 5))
      XCTAssertTrue(tagline.waitForExistence(timeout: 5))
      XCTAssertFalse(app.sheets.firstMatch.exists)
      XCTAssertGreaterThan(name.frame.minX, app.splitters.firstMatch.frame.maxX)
      XCTAssertLessThan(name.frame.maxX, window.frame.maxX - 20)
      XCTAssertGreaterThan(tagline.frame.minX, app.splitters.firstMatch.frame.maxX)
      XCTAssertLessThan(tagline.frame.maxX, window.frame.maxX - 20)
      XCTAssertTrue(app.staticTexts["Color"].exists)
      XCTAssertTrue(app.descendants(matching: .any)["bot.prompt.editor"].firstMatch.exists)
      XCTAssertTrue(app.descendants(matching: .any)["bot.tools-and-skills"].firstMatch.exists)

      app.descendants(matching: .any)["bot.prompt.editor"].firstMatch.click()
      XCTAssertTrue(app.staticTexts["Bot Prompt"].waitForExistence(timeout: 5))
      XCTAssertTrue(app.textViews["Bot prompt"].exists)
      app.buttons["Done"].click()
      XCTAssertTrue(app.descendants(matching: .any)["bot.tools-and-skills"].firstMatch.exists)

      app.descendants(matching: .any)["bot.tools-and-skills"].firstMatch.click()
      let providerConnections = ["gmail", "youtube", "google_workspace", "x"].map {
        app.descendants(matching: .any)["bot.connection.\($0)"].firstMatch
      }
      for _ in 0..<4 where providerConnections.contains(where: { !$0.exists }) {
        app.swipeUp()
      }
      for connection in providerConnections {
        XCTAssertTrue(connection.exists)
      }
      XCTAssertTrue(providerConnections[2].isHittable)
      let back = app.buttons["chevron.backward"]
      XCTAssertTrue(back.waitForExistence(timeout: 5))
      back.click()

      let close = app.buttons["sheet.close"]
      XCTAssertTrue(close.isHittable)
      close.click()
      XCTAssertTrue(close.waitForNonExistence(timeout: 5))
      XCTAssertTrue(app.buttons["chat.details"].waitForExistence(timeout: 5))
    }
  #endif
}

private extension XCUIApplication {
  func launchForUITesting() {
    launch()
    #if os(macOS)
      activate()
      if !windows.firstMatch.waitForExistence(timeout: 2) {
        let newWindow = menuBars.menuItems["New Window"]
        if newWindow.waitForExistence(timeout: 2) { newWindow.click() }
        activate()
      }
      XCTAssertTrue(windows.firstMatch.waitForExistence(timeout: 5), "The Mac test app needs a window.")
    #endif
  }
}
