// Copyright NGGT.LightKeeper. All Rights Reserved.

import { mountPushBlock } from '../push.js';
import { mountTelegramBlock } from '../telegram.js';

// Onboarding page.
// Offer the Web Push permission and the Telegram confirmation right after registration.
$(function initOnboardingPage() {
  mountPushBlock($('#pushBlock').removeClass('loading'));
  mountTelegramBlock($('#telegramBlock').removeClass('loading'));
});
