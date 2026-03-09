import React from 'react';
import './AboutSection.css';

export default function AboutSection() {
  return (
    <>
      {/* Invisible anchor for fixed-header offset */}
      <div id="about" style={{ position: 'relative', top: '-80px', visibility: 'hidden' }}></div>
      
      {/* How Jaspen Works Section */}
      <section className="about how-it-works">
        <div className="container">
          <h2 className="section-title">How Jaspen Works</h2>
          <div className="steps-grid">
            <div className="step">
              <div className="step-icon">
                <div className="step-number">1</div>
                <i className="fas fa-lightbulb"></i>
              </div>
              <h3>Input Your Idea</h3>
              <p>Describe your business concept, target market, or strategic question. Our AI understands natural language and context.</p>
            </div>
            <div className="step">
              <div className="step-icon">
                <div className="step-number">2</div>
                <i className="fas fa-cogs"></i>
              </div>
              <h3>AI Analysis Engine</h3>
              <p>Our advanced algorithms analyze market data, competitive landscape, and industry trends to provide comprehensive insights.</p>
            </div>
            <div className="step">
              <div className="step-icon">
                <div className="step-number">3</div>
                <i className="fas fa-chart-line"></i>
              </div>
              <h3>Get Actionable Results</h3>
              <p>Receive detailed reports with market viability scores, strategic recommendations, and next steps for your business.</p>
            </div>
          </div>
        </div>
      </section>

      {/* Social Proof Section */}
      <section className="about-social-proof">
        <div className="container">
          <div className="stats-grid">
            <div className="stat">
              <div className="stat-number">10,000+</div>
              <div className="stat-label">Business Ideas Analyzed</div>
            </div>
            <div className="stat">
              <div className="stat-number">500+</div>
              <div className="stat-label">Successful Validations</div>
            </div>
            <div className="stat">
              <div className="stat-number">$2M+</div>
              <div className="stat-label">Saved in Consulting Fees</div>
            </div>
            <div className="stat">
              <div className="stat-number">95%</div>
              <div className="stat-label">Customer Satisfaction</div>
            </div>
          </div>

          <div className="testimonials-grid">
            <div className="testimonial">
              <p>"Jaspen helped us validate our SaaS idea in just 24 hours. The market analysis was spot-on and saved us months of research."</p>
              <div className="testimonial-author">
                <strong>Sarah Chen</strong> - Founder, TechFlow Solutions
              </div>
            </div>
            <div className="testimonial">
              <p>"The competitive analysis feature revealed gaps we never considered. We pivoted our strategy and increased our market opportunity by 300%."</p>
              <div className="testimonial-author">
                <strong>Marcus Rodriguez</strong> - CEO, GreenTech Innovations
              </div>
            </div>
          </div>

          <div className="trust-badges">
            <div className="trust-badge">
              <i className="fas fa-shield-alt"></i>
              <span>Enterprise Security</span>
            </div>
            <div className="trust-badge">
              <i className="fas fa-clock"></i>
              <span>24/7 Support</span>
            </div>
            <div className="trust-badge">
              <i className="fas fa-award"></i>
              <span>Industry Leading</span>
            </div>
          </div>
        </div>
      </section>

      {/* About Jaspen Section */}
      <section className="about about-jaspen">
        <div className="container">
          <div className="about-header">
            <h2 className="section-title">Why 10,000+ Businesses Choose Jaspen</h2>
            <p className="section-subtitle">
              Join the fastest-growing community of data-driven decision makers
            </p>
          </div>

          <div className="about-content-grid">
            <div className="about-story">
              <h3 className="story-title">Democratizing Business Intelligence</h3>
              <p className="about-text">
                At Jaspen, we've eliminated the $50,000+ consulting fees and 6-month wait times. 
                Our AI-driven platform delivers enterprise-level market research, competitive analysis, 
                and strategic insights in minutes—not months.
              </p>
              
              <div className="value-props">
                <div className="value-prop">
                  <div className="value-icon">
                    <i className="fas fa-rocket"></i>
                  </div>
                  <div className="value-content">
                    <h4>10x Faster Insights</h4>
                    <p>Get market analysis in 5 minutes that used to take consultants 5 weeks</p>
                    <span className="value-metric">95% time reduction</span>
                  </div>
                </div>
                
                <div className="value-prop">
                  <div className="value-icon">
                    <i className="fas fa-shield-alt"></i>
                  </div>
                  <div className="value-content">
                    <h4>Enterprise Security</h4>
                    <p>Bank-level encryption with SOC 2 compliance for your sensitive data</p>
                    <span className="value-metric">99.9% uptime SLA</span>
                  </div>
                </div>
                
                <div className="value-prop">
                  <div className="value-icon">
                    <i className="fas fa-chart-line"></i>
                  </div>
                  <div className="value-content">
                    <h4>Proven Results</h4>
                    <p>Our users see 3.2x higher success rates in product launches</p>
                    <span className="value-metric">320% improvement</span>
                  </div>
                </div>
              </div>
            </div>

            <div className="testimonial-highlight">
              <div className="testimonial-content">
                <div className="quote-icon">"</div>
                <p className="testimonial-text">
                  "Jaspen helped us validate our market fit and launch 3x faster than our competitors. 
                  The ROI was immediate."
                </p>
                <div className="testimonial-author">
                  <strong>Sarah Chen</strong> - CEO, TechFlow
                </div>
              </div>
            </div>
          </div>

          <div className="cta-section">
            <h3 className="cta-title">Ready to 10x Your Business Intelligence?</h3>
            <p className="cta-subtitle">Join 500+ companies who upgraded their strategy this month</p>
            <div className="cta-buttons">
              <button className="btn btn-primary-large">Start Free Trial</button>
              <button className="btn btn-secondary-outline">View Success Stories</button>
            </div>
            <div className="urgency-text">⚡ Limited: Only 50 founder spots remaining this quarter</div>
          </div>
        </div>
      </section>
    </>
  );
}
