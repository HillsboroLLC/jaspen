import React from 'react';
import './terms.css';

const Terms = () => {
  return (
    <div className="terms-container">
      <div className="terms-content">
        <h1>Terms of Service for Gridd</h1>

        <div className="terms-meta">
          <p><strong>Effective Date:</strong> September 15, 2025<br />
          <strong>Last Updated:</strong> September 15, 2025</p>
        </div>

        <section className="terms-section">
          <h2>Agreement to Terms</h2>
          <p>These Terms of Service ("Terms") constitute a legally binding agreement between you ("User," "you," or "your") and Sekki LLC ("Company," "we," "us," or "our") regarding your use of the Gridd mobile application (the "App").</p>
          <p>By downloading, installing, or using our App, you agree to be bound by these Terms. If you do not agree to these Terms, do not use our App.</p>
        </section>

        <section className="terms-section">
          <h2>Description of Service</h2>
          <p>Gridd is a mobile puzzle game application that provides:</p>
          <ul>
            <li>Classic Sudoku puzzles with multiple difficulty levels</li>
            <li>Game progress tracking and statistics</li>
            <li>Hint system and gameplay assistance features</li>
            <li>In-app purchases for additional content and features</li>
            <li>Advertisement-supported free gameplay</li>
            <li>Token-based reward system</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>User Accounts and Registration</h2>
          <ul>
            <li>No account registration is required to use the basic features of our App</li>
            <li>Game progress and preferences are stored locally on your device</li>
            <li>You are responsible for maintaining the security of your device and any data stored on it</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Acceptable Use</h2>
          
          <h3>You May:</h3>
          <ul>
            <li>Use the App for personal, non-commercial entertainment purposes</li>
            <li>Share your achievements and progress with others</li>
            <li>Provide feedback and suggestions for improvement</li>
          </ul>

          <h3>You May Not:</h3>
          <ul>
            <li>Use the App for any illegal or unauthorized purpose</li>
            <li>Attempt to reverse engineer, decompile, or hack the App</li>
            <li>Use automated tools or bots to interact with the App</li>
            <li>Interfere with or disrupt the App's functionality</li>
            <li>Violate any applicable laws or regulations while using the App</li>
            <li>Use the App to transmit harmful, offensive, or inappropriate content</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>In-App Purchases and Virtual Currency</h2>
          
          <h3>Token System</h3>
          <ul>
            <li>Our App uses a virtual currency system called "tokens"</li>
            <li>Tokens can be earned through gameplay or purchased with real money</li>
            <li>Tokens can be used to purchase hints, unlock features, or access premium content</li>
            <li>Tokens have no real-world value and cannot be exchanged for cash</li>
          </ul>

          <h3>In-App Purchases</h3>
          <ul>
            <li>All in-app purchases are processed through Apple's App Store</li>
            <li>Purchases are final and non-refundable except as required by applicable law</li>
            <li>We do not store your payment information; all transactions are handled by Apple</li>
            <li>Prices for in-app purchases may change without notice</li>
          </ul>

          <h3>Available Purchase Options:</h3>
          <ul>
            <li>Remove Advertisements</li>
            <li>Token Packages (various amounts)</li>
            <li>Premium Features and Content</li>
          </ul>

          <h3>Refund Policy</h3>
          <ul>
            <li>Refund requests must be made through Apple's App Store</li>
            <li>We follow Apple's standard refund policies</li>
            <li>Refunds are at Apple's sole discretion</li>
            <li>Virtual items purchased with tokens are non-refundable</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Advertising</h2>
          <ul>
            <li>Our App displays third-party advertisements through Google AdMob</li>
            <li>We do not control the content of advertisements</li>
            <li>Clicking on ads may redirect you to external websites</li>
            <li>We are not responsible for the content or practices of advertisers</li>
            <li>You may limit ad personalization through your device settings</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Intellectual Property Rights</h2>
          
          <h3>Our Rights</h3>
          <ul>
            <li>The App and all its content, features, and functionality are owned by Sekki LLC</li>
            <li>All trademarks, logos, and service marks are our property or our licensors'</li>
            <li>The App is protected by copyright, trademark, and other intellectual property laws</li>
          </ul>

          <h3>Your Rights</h3>
          <ul>
            <li>You are granted a limited, non-exclusive, non-transferable license to use the App</li>
            <li>This license is for personal, non-commercial use only</li>
            <li>You may not copy, modify, distribute, or create derivative works from the App</li>
          </ul>

          <h3>User-Generated Content</h3>
          <ul>
            <li>Any feedback, suggestions, or ideas you provide become our property</li>
            <li>We may use your suggestions without compensation or attribution</li>
            <li>You retain ownership of any personal data you input into the App</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Privacy and Data Protection</h2>
          <p>Your privacy is important to us. Our collection and use of information is governed by our Privacy Policy, which is incorporated into these Terms by reference. Please review our Privacy Policy to understand our data practices.</p>
        </section>

        <section className="terms-section">
          <h2>Disclaimers and Limitations of Liability</h2>
          
          <h3>App Availability</h3>
          <ul>
            <li>We strive to keep the App available 24/7 but cannot guarantee uninterrupted service</li>
            <li>The App may be temporarily unavailable due to maintenance, updates, or technical issues</li>
            <li>We reserve the right to modify or discontinue the App at any time</li>
          </ul>

          <h3>Disclaimer of Warranties</h3>
          <p className="legal-text">THE APP IS PROVIDED "AS IS" AND "AS AVAILABLE" WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, AND NON-INFRINGEMENT.</p>

          <h3>Limitation of Liability</h3>
          <p className="legal-text">TO THE MAXIMUM EXTENT PERMITTED BY LAW, SEKKI LLC SHALL NOT BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING BUT NOT LIMITED TO LOSS OF DATA, LOSS OF PROFITS, OR BUSINESS INTERRUPTION.</p>
        </section>

        <section className="terms-section">
          <h2>Termination</h2>
          
          <h3>By You</h3>
          <ul>
            <li>You may stop using the App at any time by deleting it from your device</li>
            <li>Uninstalling the App will remove all locally stored data</li>
          </ul>

          <h3>By Us</h3>
          <p>We may terminate or suspend your access to the App immediately, without prior notice, if you:</p>
          <ul>
            <li>Violate these Terms of Service</li>
            <li>Engage in fraudulent or illegal activities</li>
            <li>Use the App in a manner that could damage our reputation or business</li>
          </ul>

          <h3>Effect of Termination</h3>
          <ul>
            <li>Upon termination, your right to use the App ceases immediately</li>
            <li>All provisions of these Terms that should survive termination will remain in effect</li>
            <li>Termination does not affect any rights or obligations that arose before termination</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Updates and Modifications</h2>
          
          <h3>App Updates</h3>
          <ul>
            <li>We may release updates to improve functionality, fix bugs, or add new features</li>
            <li>Updates may be required for continued use of the App</li>
            <li>You are responsible for downloading and installing updates</li>
          </ul>

          <h3>Terms Updates</h3>
          <ul>
            <li>We reserve the right to modify these Terms at any time</li>
            <li>Changes will be effective immediately upon posting in the App</li>
            <li>Your continued use of the App after changes constitutes acceptance of the new Terms</li>
            <li>We will notify you of significant changes through the App or other reasonable means</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Governing Law and Dispute Resolution</h2>
          
          <h3>Governing Law</h3>
          <p>These Terms are governed by and construed in accordance with the laws of North Carolina, United States, without regard to conflict of law principles.</p>

          <h3>Dispute Resolution</h3>
          <ul>
            <li>Any disputes arising from these Terms or your use of the App will be resolved through binding arbitration</li>
            <li>Arbitration will be conducted by a single arbitrator in North Carolina, United States</li>
            <li>You waive any right to participate in class-action lawsuits or class-wide arbitration</li>
          </ul>

          <h3>Exceptions</h3>
          <p>The following disputes are not subject to arbitration:</p>
          <ul>
            <li>Disputes related to intellectual property rights</li>
            <li>Small claims court actions</li>
            <li>Injunctive relief requests</li>
          </ul>
        </section>

        <section className="terms-section">
          <h2>Apple App Store Terms</h2>
          <p>If you downloaded the App from the Apple App Store, the following additional terms apply:</p>
          
          <h3>License</h3>
          <ul>
            <li>The license granted is limited to a non-transferable license to use the App on Apple-branded products</li>
            <li>Apple is not responsible for the App or its content</li>
            <li>Apple has no obligation to provide maintenance or support for the App</li>
          </ul>

          <h3>Product Claims</h3>
          <ul>
            <li>We, not Apple, are responsible for addressing any claims relating to the App</li>
            <li>Apple is not responsible for investigating, defending, settling, or discharging any third-party claims</li>
          </ul>

          <h3>Intellectual Property</h3>
          <p>If a third party claims the App infringes their intellectual property rights, we, not Apple, will be responsible for the investigation and resolution</p>
        </section>

        <section className="terms-section">
          <h2>Contact Information</h2>
          <p>If you have any questions about these Terms of Service, please contact us:</p>
          <div className="contact-info">
            <p><strong>Sekki LLC</strong><br />
            Email: hello@jaspen.ai<br />
            Website: <a href="https://jaspen.ai" target="_blank" rel="noopener noreferrer">https://jaspen.ai</a><br />
            Address: 4030 Wake Forest Road, STE 349, Raleigh, NC 27609, USA<br />
            Phone: +1 (704) 488-5799</p>
          </div>
        </section>

        <section className="terms-section">
          <h2>Severability</h2>
          <p>If any provision of these Terms is found to be unenforceable or invalid, that provision will be limited or eliminated to the minimum extent necessary so that these Terms will otherwise remain in full force and effect.</p>
        </section>

        <section className="terms-section">
          <h2>Entire Agreement</h2>
          <p>These Terms, together with our Privacy Policy, constitute the entire agreement between you and Sekki LLC regarding the use of the App and supersede all prior agreements and understandings.</p>
        </section>

        <hr className="terms-divider" />

        <div className="terms-footer">
          <p><em>These Terms of Service were last updated on September 15, 2025. Please review them periodically for any changes.</em></p>
        </div>
      </div>
    </div>
  );
};

export default Terms;
