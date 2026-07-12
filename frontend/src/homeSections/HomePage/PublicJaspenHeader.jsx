import React from 'react';
import JaspenNav from './JaspenNav';
import usePublicAuthModal from './usePublicAuthModal';

export default function PublicJaspenHeader() {
  const { openAuthModal, AuthModalPortal } = usePublicAuthModal();

  return (
    <div className="public-jaspen-header">
      <JaspenNav onOpenModal={openAuthModal} />
      {AuthModalPortal}
    </div>
  );
}
