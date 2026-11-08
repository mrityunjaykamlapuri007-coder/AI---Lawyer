# Demo attempt 1 (kept)

Revealed two defects, fixed in 6a76497: the LLM returned support_contact_made=True for "I have not contacted them yet" (screenshot chat got a formal grievance instead of informal); all chats shared one demo user, so the bait chat was treated as a possible second order and the guards were not exercised.
