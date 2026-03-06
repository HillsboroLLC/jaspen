import React, { useState } from 'react';
import { CardElement, useStripe, useElements } from '@stripe/react-stripe-js';
import Spinner from '../Spinner/Spinner';
import { API_BASE } from '../../config/apiBase';
import './CheckoutForm.css';

export default function CheckoutForm() {
  const stripe = useStripe();
  const elements = useElements();
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [success, setSuccess] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!stripe || !elements) return;

    setLoading(true);
    setErrorMsg('');

    // Create PaymentIntent on the server
    const res = await fetch(`${API_BASE}/api/billing/create-payment-intent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ amount: 1000 })  // sample amount
    });
    const { client_secret } = await res.json();

    const card = elements.getElement(CardElement);
    const { error, paymentIntent } = await stripe.confirmCardPayment(client_secret, {
      payment_method: { card }
    });

    setLoading(false);
    if (error) {
      setErrorMsg(error.message);
    } else if (paymentIntent && paymentIntent.status === 'succeeded') {
      setSuccess(true);
    }
  };

  if (loading) return <Spinner />;

  if (success) {
    return <div className="checkout-success">Payment succeeded! 🎉</div>;
  }

  return (
    <form className="checkout-form" onSubmit={handleSubmit}>
      <CardElement options={{ hidePostalCode: true }} />
      {errorMsg && <div className="card-error">{errorMsg}</div>}
      <button type="submit" disabled={!stripe}>Pay</button>
    </form>
  );
}
