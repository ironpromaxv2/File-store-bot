# Password Hashing in MVC

## Overview
Password hashing is critical for user authentication. Never store plain text passwords.

## Implementation
1. Install bcrypt:
   ```bash
   npm install bcrypt
   ```
2. Use bcrypt in your authentication logic:
   ```javascript
   const bcrypt = require('bcrypt');
   // To hash a password
   const hashedPassword = await bcrypt.hash(password, saltRounds);
   
   // To compare passwords
   const match = await bcrypt.compare(password, hashedPassword);
   ```

## Important Considerations
- Use a secure method in your application settings to manage salt rounds.
- Regularly update your hashing algorithms to stay ahead of vulnerabilities.