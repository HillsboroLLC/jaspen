import React from 'react';
import './privacy.css';

const Privacy = () => {
  return (
    <div className="privacy-container">
      <div className="privacy-content">
        <h1>Privacy Policy for Gridd</h1>

        <div className="policy-meta">
          <p><strong>Effective Date:</strong> September 15, 2025<br />
          <strong>Last Updated:</strong> September 15, 2025</p>
        </div>

        <section className="policy-section">
          <h2>Introduction</h2>
          <p>Sekki LLC ("we," "our," or "us") operates the Gridd mobile application (the "App"). This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you use our App.</p>
          <p>By using Gridd, you agree to the collection and use of information in accordance with this Privacy Policy. If you do not agree with our policies and practices, do not download, register with, or use this App.</p>
        </section>

        <section className="policy-section">
          <h2>Information We Collect</h2>
          
          <h3>Information You Provide Directly</h3>
          <ul>
            <li><strong>Game Progress Data:</strong> Your puzzle completion times, difficulty preferences, game statistics, and saved game states</li>
            <li><strong>Settings and Preferences:</strong> Your chosen themes, sound settings, haptic feedback preferences, and other customization options</li>
            <li><strong>Purchase Information:</strong> Records of in-app purchases and token transactions (processed through Apple's App Store)</li>
          </ul>

          <h3>Information Collected Automatically</h3>
          <ul>
            <li><strong>Device Information:</strong> Device type, operating system version, unique device identifiers</li>
            <li><strong>Usage Data:</strong> App usage patterns, feature interactions, session duration, and crash reports</li>
            <li><strong>Performance Data:</strong> App performance metrics and error logs for improving user experience</li>
          </ul>

          <h3>Information from Third-Party Services</h3>
          
          <h4>Google AdMob</h4>
          <p>Our App displays advertisements through Google AdMob. Google may collect:</p>
          <ul>
            <li>Device advertising identifiers (IDFA on iOS)</li>
            <li>IP address and approximate location</li>
            <li>App usage data for ad targeting and measurement</li>
            <li>Device and network information</li>
          </ul>
          <p>For more information about Google's data practices, please review Google's Privacy Policy at <a href="https://policies.google.com/privacy" target="_blank" rel="noopener noreferrer">https://policies.google.com/privacy</a></p>

          <h4>Apple App Store</h4>
          <p>When you make in-app purchases, Apple processes your payment information according to Apple's Privacy Policy. We receive confirmation of purchases but do not have access to your payment details.</p>
        </section>

        <section className="policy-section">
          <h2>How We Use Your Information</h2>
          
          <h3>Core App Functionality</h3>
          <ul>
            <li>Saving your game progress and statistics</li>
            <li>Providing personalized difficulty recommendations</li>
            <li>Maintaining your preferences and settings across app sessions</li>
            <li>Enabling game features like hints, undo/redo, and timers</li>
          </ul>

          <h3>App Improvement</h3>
          <ul>
            <li>Analyzing usage patterns to improve game features</li>
            <li>Identifying and fixing technical issues</li>
            <li>Optimizing app performance and user experience</li>
          </ul>

          <h3>Advertising</h3>
          <ul>
            <li>Displaying relevant advertisements through Google AdMob</li>
            <li>Measuring ad performance and effectiveness</li>
            <li>Supporting our free-to-play business model</li>
          </ul>

          <h3>Legal and Safety</h3>
          <ul>
            <li>Complying with applicable laws and regulations</li>
            <li>Protecting against fraud and abuse</li>
            <li>Enforcing our Terms of Service</li>
          </ul>
        </section>

        <section className="policy-section">
          <h2>Data Storage and Security</h2>
          
          <h3>Local Storage</h3>
          <p>Most of your game data is stored locally on your device using secure storage mechanisms:</p>
          <ul>
            <li>Game progress and statistics</li>
            <li>User preferences and settings</li>
            <li>Token balances and purchase records</li>
          </ul>

          <h3>Data Security</h3>
          <p>We implement appropriate technical and organizational security measures to protect your information:</p>
          <ul>
            <li>Encryption of sensitive data</li>
            <li>Secure data transmission protocols</li>
            <li>Regular security assessments and updates</li>
            <li>Limited access to personal information</li>
          </ul>

          <h3>Data Retention</h3>
          <ul>
            <li>Game data is retained locally on your device until you delete the app</li>
            <li>We do not store personal information on our servers</li>
            <li>Third-party services (Google AdMob) retain data according to their own policies</li>
          </ul>
        </section>

        <section className="policy-section">
          <h2>Sharing Your Information</h2>
          <p>We do not sell, trade, or otherwise transfer your personal information to third parties, except:</p>
          
          <h3>Service Providers</h3>
          <ul>
            <li><strong>Google AdMob:</strong> For displaying advertisements (see their privacy policy)</li>
            <li><strong>Apple:</strong> For processing in-app purchases (see Apple's privacy policy)</li>
          </ul>

          <h3>Legal Requirements</h3>
          <p>We may disclose your information if required by law or in response to valid legal requests from public authorities.</p>

          <h3>Business Transfers</h3>
          <p>In the event of a merger, acquisition, or sale of assets, user information may be transferred as part of the transaction.</p>
        </section>

        <section className="policy-section">
          <h2>Your Privacy Rights</h2>
          
          <h3>Access and Control</h3>
          <ul>
            <li><strong>Game Data:</strong> You can view your statistics and progress within the app</li>
            <li><strong>Settings:</strong> You can modify preferences and settings at any time</li>
            <li><strong>Data Deletion:</strong> Uninstalling the app removes all locally stored data</li>
          </ul>

          <h3>Advertising Choices</h3>
          <ul>
            <li><strong>iOS:</strong> You can limit ad tracking in Settings &gt; Privacy &amp; Security &gt; Apple Advertising</li>
            <li><strong>Opt-out:</strong> You can opt out of personalized ads through Google's Ad Settings</li>
          </ul>

          <h3>Contact Us</h3>
          <p>If you have questions about your data or wish to exercise your privacy rights, contact us at hello@jaspen.ai.</p>
        </section>

        <section className="policy-section">
          <h2>Children's Privacy</h2>
          <p>Gridd is suitable for all ages, including children. We do not knowingly collect personal information from children under 13 without parental consent. The app:</p>
          <ul>
            <li>Does not require account creation or personal information</li>
            <li>Uses family-friendly advertisements</li>
            <li>Complies with COPPA (Children's Online Privacy Protection Act)</li>
          </ul>
          <p>If you believe we have collected information from a child under 13, please contact us immediately.</p>
        </section>

        <section className="policy-section">
          <h2>International Users</h2>
          <p>If you are using our App from outside the United States, please note that your information may be transferred to, stored, and processed in the United States where our servers are located and our central database is operated.</p>
        </section>

        <section className="policy-section">
          <h2>Changes to This Privacy Policy</h2>
          <p>We may update this Privacy Policy from time to time. We will notify you of any changes by:</p>
          <ul>
            <li>Posting the new Privacy Policy in the app</li>
            <li>Updating the "Last Updated" date</li>
            <li>Providing notice through the app or other reasonable means</li>
          </ul>
          <p>Your continued use of the App after any modifications indicates your acceptance of the updated Privacy Policy.</p>
        </section>

        <section className="policy-section">
          <h2>Third-Party Links and Services</h2>
          <p>Our App may contain links to third-party websites or services. We are not responsible for the privacy practices of these third parties. We encourage you to read their privacy policies.</p>
        </section>

        <section className="policy-section">
          <h2>Contact Information</h2>
          <p>If you have any questions about this Privacy Policy, please contact us:</p>
          <div className="contact-info">
            <p><strong>Sekki LLC</strong><br />
            Email: hello@jaspen.ai<br />
            Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">https://jaspen.ai</a><br />
            Address: 4030 Wake Forest Road, STE 349, Raleigh, NC 27609, USA</p>
          </div>
        </section>

        <section className="policy-section">
          <h2>Compliance</h2>
          <p>This Privacy Policy complies with:</p>
          <ul>
            <li>Apple App Store Review Guidelines</li>
            <li>Google AdMob Policies</li>
            <li>California Consumer Privacy Act (CCPA)</li>
            <li>General Data Protection Regulation (GDPR)</li>
            <li>Children's Online Privacy Protection Act (COPPA)</li>
          </ul>
        </section>

        <hr className="policy-divider" />

        <div className="policy-footer">
          <p><em>This Privacy Policy was last updated on September 15, 2025. Please review it periodically for any changes.</em></p>
        </div>
      </div>
    </div>
  );
};

export default Privacy;
