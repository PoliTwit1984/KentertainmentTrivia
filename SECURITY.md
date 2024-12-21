# Security Notice

## Sensitive Data Cleanup Required

The repository contains sensitive data in its git history that needs to be removed:

1. Azure Cosmos DB Keys in:
   - docker-compose.yml:16
   - docker-compose.yml:40
   - docker-compose.yml:66
   - run_tests.sh:5

2. Azure Storage Account Keys in:
   - docker-compose.yml:18
   - docker-compose.yml:42
   - docker-compose.yml:68

### Quick Reset Method (Recommended for Fresh Start)

1. Backup your current code (without git history):
```bash
# Create a backup of your current code
cp -r . ../KentertainmentTrivia-backup
```

2. Remove git history and start fresh:
```bash
# Remove all git history
rm -rf .git

# Initialize fresh git repository
git init

# Add template files first
git add docker-compose.template.yml run_tests.sh.template SECURITY.md .gitignore project.md
git commit -m "Initial commit with template files"

# Add remaining code files
git add .
git commit -m "Add project code"

# Set up remote and push
git remote add origin https://github.com/PoliTwit1984/KentertainmentTrivia.git
git push -f origin main
```

3. Set up your local environment:
```bash
# Create your local config files from templates
cp docker-compose.template.yml docker-compose.yml
cp run_tests.sh.template run_tests.sh
chmod +x run_tests.sh

# Create and edit your .env file
echo "COSMOS_ENDPOINT=your_endpoint" > .env
echo "COSMOS_KEY=your_key" >> .env
```

### Alternative Cleanup Methods

#### Method 1: Using BFG Repo-Cleaner (Recommended)

1. Create a backup of your repository:
```bash
# Create a backup
cp -r your-repo your-repo-backup
```

2. Download BFG Repo-Cleaner:
```bash
wget https://repo1.maven.org/maven2/com/madgag/bfg/1.14.0/bfg-1.14.0.jar
mv bfg-1.14.0.jar bfg.jar
```

3. Create a text file with sensitive data patterns:
```bash
# secrets.txt
YOUR_COSMOS_DB_KEY_HERE
YOUR_COSMOS_DB_ENDPOINT_HERE
```

4. Run BFG to remove sensitive data:
```bash
# First, clone a fresh copy of your repo
git clone --mirror git@github.com:your-username/your-repo.git

# Run BFG
java -jar bfg.jar --replace-text secrets.txt your-repo.git

# Clean up
cd your-repo.git
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push --force
```

#### Method 2: Using git filter-branch

1. Create a backup branch:
```bash
git checkout -b backup_main
git push origin backup_main
```

2. Remove sensitive files from git history:
```bash
# Remove the files from git history
git filter-branch --force --index-filter \
'git rm --cached --ignore-unmatch docker-compose.yml run_tests.sh' \
--prune-empty --tag-name-filter cat -- --all

# Clean up the backup refs
git for-each-ref --format='delete %(refname)' refs/original | git update-ref --stdin
git reflog expire --expire=now --all
git gc --prune=now --aggressive
```

3. Verify the sensitive data is removed:
```bash
git log -p | grep -i cosmos
git log -p | grep -i storage
```

4. Force push the changes:
```bash
# First, ensure you're on main branch
git checkout main

# Force push to remote, overwriting history
git push origin main --force

# Force push tags if needed
git push origin --force --tags
```

5. Collaborators need to reset their local repos:
```bash
# For each collaborator
git fetch origin
git reset --hard origin/main
git clean -fd
```

3. Set up your local environment:
```bash
# Copy templates
cp docker-compose.template.yml docker-compose.yml
cp run_tests.sh.template run_tests.sh

# Create .env file with your credentials
echo "COSMOS_ENDPOINT=your_endpoint" > .env
echo "COSMOS_KEY=your_key" >> .env

# Make run_tests.sh executable
chmod +x run_tests.sh
```

4. Update your credentials:
   - Edit docker-compose.yml with your actual values
   - Create .env file with your credentials
   - Never commit these files (they're gitignored)

### Prevention

1. Use environment variables for sensitive data
2. Keep docker-compose.yml in .gitignore
3. Use template files for configuration
4. Review changes before committing
5. Enable GitHub's secret scanning feature
