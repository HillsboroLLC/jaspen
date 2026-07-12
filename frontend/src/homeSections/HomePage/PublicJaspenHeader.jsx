import React from 'react';
import JaspenNav from './JaspenNav';
import usePublicAuthModal from './usePublicAuthModal';

export default function PublicJaspenHeader() {
  const { openAuthModal, AuthModalPortal } = usePublicAuthModal();

  return (
    <>
      <JaspenNav onOpenModal={openAuthModal} />
      {AuthModalPortal}
    </>
  );
}
